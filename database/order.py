"""
Order insertion and status management functions for parent and child order tables.

This module handles all database operations for parent and child orders,
including creation, insertion, batch operations, and status updates.
It manages the parent-child order relationship for the trading engine.

Classes:
    None (module contains functions only)

Functions:
    create_order_parent_table: Create the order_parent table
    create_order_child_table: Create the order_child table
    insert_order_parent: Insert a single parent order
    insert_order_child: Insert a single child order
    insert_order_parent_batch: Insert multiple parent orders
    insert_order_child_batch: Insert multiple child orders
    get_parent_order: Retrieve a parent order by ID
    get_parent_orders: Retrieve all parent orders
    get_child_orders: Retrieve child orders for a parent
    update_order_parent_status: Update parent order status
    update_order_parent_status_batch: Update multiple parent order statuses
    update_order_child_status: Update child order status
    update_order_child_status_batch: Update multiple child order statuses
"""

from database.database import PostgresDB
from typing import Dict, List, Any, Optional

DB_CLIENT: PostgresDB = PostgresDB()


def create_order_parent_table() -> None:
    """
    Create the order_parent table if it doesn't exist.
    
    Creates a table for tracking parent orders with columns for:
    - Order identification (id, client_order_id)
    - Order details (product_id, side, size, price, status)
    - Target movement configuration (target_movement, target_movement_type)
    - Timestamp (created_at)
    
    Returns:
        None
    """
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
    """
    Create the order_child table if it doesn't exist.
    
    Creates a table for tracking child orders with:
    - Foreign key reference to parent order
    - Order identification (id, client_order_id)
    - Order details (product_id, side, size, price, status)
    - Timestamp (created_at)
    
    Returns:
        None
    """
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
    
    Creates a new parent order record with specified parameters.
    Parent orders track the top-level trading action and can have multiple
    child orders associated with them.
    
    Args:
        client_order_id: Unique client-assigned order identifier (UUID).
        product_id: Trading pair identifier (e.g., 'BTC-USDC', 'BIP-20DEC30-CDE').
        side: Order side - 'BUY' or 'SELL'.
        size: Order size/quantity.
        price: Order price.
        target_movement: Target price movement for follow-up orders.
        target_movement_type: Type of target movement - 'P' for percentage (default),
                             'A' for absolute dollar amount.
        status: Order status (default: 'pending'). Common values:
               'pending', 'open', 'filled', 'cancelled', 'failed'.
    
    Returns:
        The inserted row's serial ID on success, None on failure.
    
    Example:
        >>> order_id = insert_order_parent(
        ...     client_order_id='550e8400-e29b-41d4-a716-446655440000',
        ...     product_id='BTC-USDC',
        ...     side='BUY',
        ...     size=1.5,
        ...     price=50000.00,
        ...     target_movement=0.02,
        ...     target_movement_type='P',
        ...     status='open'
        ... )
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
    
    Creates a new child order associated with a parent order.
    Child orders are follow-up orders created in response to parent order fills
    or cancellations as part of the trading strategy.
    
    Args:
        parent_client_order_id: The parent order's client_order_id (must exist in order_parent).
        client_order_id: Unique child order identifier (UUID).
        product_id: Trading pair identifier (e.g., 'BTC-USDC').
        side: Order side - 'BUY' or 'SELL'.
        size: Order size/quantity.
        price: Order price.
        status: Order status (default: 'pending'). Common values:
               'pending', 'open', 'filled', 'cancelled', 'failed'.
    
    Returns:
        The inserted row's serial ID on success, None on failure.
    
    Raises:
        Exception: If parent_client_order_id doesn't exist in order_parent table
                  (foreign key constraint violation).
    
    Example:
        >>> child_id = insert_order_child(
        ...     parent_client_order_id='550e8400-e29b-41d4-a716-446655440000',
        ...     client_order_id='660e8400-e29b-41d4-a716-446655440111',
        ...     product_id='BTC-USDC',
        ...     side='SELL',
        ...     size=1.5,
        ...     price=51000.00,
        ...     status='open'
        ... )
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
    
    Processes a list of parent order dictionaries and inserts them individually.
    Invalid orders are skipped with a warning.
    
    Args:
        orders: List of parent order dictionaries with keys:
               - client_order_id (required): UUID
               - product_id (required): Trading pair
               - side (required): 'BUY' or 'SELL'
               - size (required): Order quantity
               - price (required): Order price
               - target_movement (required): Target movement amount
               - status (optional, default: 'pending')
               - target_movement_type (optional, default: 'P')
    
    Returns:
        List of inserted row IDs (None for any that failed or were skipped).
        Length matches input list.
    
    Example:
        >>> ids = insert_order_parent_batch([
        ...     {
        ...         'client_order_id': '550e8400-e29b-41d4-a716-446655440000',
        ...         'product_id': 'BTC-USDC',
        ...         'side': 'BUY',
        ...         'size': 1.0,
        ...         'price': 50000.0,
        ...         'target_movement': 0.02,
        ...         'status': 'open'
        ...     },
        ...     # ... more orders
        ... ])
    """
    inserted_ids: List[Optional[int]] = []
    
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
    
    Processes a list of child order dictionaries and inserts them individually.
    Invalid orders are skipped with a warning.
    
    Args:
        orders: List of child order dictionaries with keys:
               - parent_client_order_id (required)
               - client_order_id (required)
               - product_id (required)
               - side (required)
               - size (required)
               - price (required)
               - status (optional, default: 'pending')
    
    Returns:
        Total number of rows successfully inserted.
    
    Example:
        >>> total = insert_order_child_batch([
        ...     {
        ...         'parent_client_order_id': '550e8400-e29b-41d4-a716-446655440000',
        ...         'client_order_id': '660e8400-e29b-41d4-a716-446655440111',
        ...         'product_id': 'BTC-USDC',
        ...         'side': 'SELL',
        ...         'size': 1.0,
        ...         'price': 51000.0
        ...     },
        ...     # ... more orders
        ... ])
    """
    total_inserted: int = 0
    
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
        if result is not None:
            total_inserted += 1
    
    return total_inserted


def get_parent_order(client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a parent order by client_order_id.
    
    Fetches a single parent order record from the database.
    
    Args:
        client_order_id: The parent order's unique client identifier.
    
    Returns:
        Order record as dictionary if found, None otherwise.
    
    Example:
        >>> order = get_parent_order('550e8400-e29b-41d4-a716-446655440000')
        >>> if order:
        ...     print(f"Order status: {order['status']}")
    """
    query = "SELECT * FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return results[0] if results else None


def get_parent_orders() -> List[Dict[str, Any]]:
    """
    Retrieve all parent orders from the database.
    
    Fetches all parent order records without filtering.
    
    Returns:
        List of parent order records as dictionaries. Empty list if no orders exist.
    
    Example:
        >>> orders = get_parent_orders()
        >>> for order in orders:
        ...     print(f"{order['client_order_id']}: {order['status']}")
    """
    query = "SELECT * FROM order_parent"
    return DB_CLIENT.execute_query(query)


def get_child_orders(parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all child orders for a parent order.
    
    Fetches all child orders associated with a specific parent order ID.
    
    Args:
        parent_client_order_id: The parent order's unique client identifier.
    
    Returns:
        List of child order records as dictionaries. Empty list if no children exist.
    
    Example:
        >>> children = get_child_orders('550e8400-e29b-41d4-a716-446655440000')
        >>> print(f"Parent has {len(children)} child orders")
    """
    query = "SELECT * FROM order_child WHERE parent_client_order_id = %s"
    return DB_CLIENT.execute_query(query, (parent_client_order_id,))


def update_order_parent_status(
    client_order_id: str,
    status: str
) -> int:
    """
    Update the status of a parent order.
    
    Changes the status field for a parent order identified by client_order_id.
    
    Args:
        client_order_id: The parent order's unique client identifier.
        status: New status value (e.g., 'pending', 'open', 'filled', 'cancelled', 'failed').
    
    Returns:
        Number of rows updated (1 on success, 0 if order not found).
    
    Example:
        >>> updated = update_order_parent_status(
        ...     '550e8400-e29b-41d4-a716-446655440000',
        ...     'filled'
        ... )
        >>> print(f"Updated {updated} order(s)")
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
    
    Processes a list of status updates and applies them individually.
    Invalid updates are skipped with a warning.
    
    Args:
        status_updates: List of update dictionaries with keys:
                       - client_order_id (required)
                       - status (required)
    
    Returns:
        Total number of rows updated.
    
    Example:
        >>> total = update_order_parent_status_batch([
        ...     {'client_order_id': '550e8400-e29b-41d4-a716-446655440000', 'status': 'filled'},
        ...     {'client_order_id': '550e8400-e29b-41d4-a716-446655440001', 'status': 'cancelled'},
        ... ])
    """
    total_updated: int = 0
    
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
    
    Changes the status field for a child order identified by client_order_id.
    
    Args:
        client_order_id: The child order's unique client identifier.
        status: New status value (e.g., 'pending', 'open', 'filled', 'cancelled', 'failed').
    
    Returns:
        Number of rows updated (1 on success, 0 if order not found).
    
    Example:
        >>> updated = update_order_child_status(
        ...     '660e8400-e29b-41d4-a716-446655440111',
        ...     'filled'
        ... )
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
    
    Processes a list of status updates and applies them individually.
    Invalid updates are skipped with a warning.
    
    Args:
        status_updates: List of update dictionaries with keys:
                       - client_order_id (required)
                       - status (required)
    
    Returns:
        Total number of rows updated.
    
    Example:
        >>> total = update_order_child_status_batch([
        ...     {'client_order_id': '660e8400-e29b-41d4-a716-446655440111', 'status': 'filled'},
        ...     {'client_order_id': '660e8400-e29b-41d4-a716-446655440112', 'status': 'cancelled'},
        ... ])
    """
    total_updated: int = 0
    
    for update in status_updates:
        client_order_id = update.get('client_order_id')
        status = update.get('status')
        
        if not all([client_order_id, status]):
            print(f"Skipping invalid status update: {update}")
            continue
        
        result = update_order_child_status(client_order_id, status)
        total_updated += result
    
    return total_updated
