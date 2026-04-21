"""
Order insertion and status management functions for parent and child order tables.

This module handles all database operations for parent and child orders,
including creation, insertion, batch operations, duplicate detection,
replacement tracking, and status updates.
It manages the parent-child order relationship for the trading engine.
"""

from logging_service import get_logger
from database.database import PostgresDB
from typing import Dict, List, Any, Optional
from core.constants import get_local_now

logger = get_logger("OrderDB")
DB_CLIENT: PostgresDB = PostgresDB()


def create_order_parent_table() -> None:
    """
    Create the order_parent table if it doesn't exist.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_parent (
        id SERIAL PRIMARY KEY,
        target_movement NUMERIC,
        target_movement_type VARCHAR(1),
        max_order_replacement INTEGER NOT NULL DEFAULT 0,
        current_order_replacement INTEGER NOT NULL DEFAULT 0,
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
    
    Includes adoption tracking columns for greenfield deployments:
    - previous_parent_client_order_id: Stores original parent before adoption
    - adopted_at: Timestamp when adoption occurred
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
        previous_parent_client_order_id VARCHAR(40) DEFAULT NULL,
        adopted_at TIMESTAMP DEFAULT NULL,
        FOREIGN KEY (parent_client_order_id) REFERENCES order_parent(client_order_id)
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_child table done.")


def create_stealth_orders_table() -> None:
    """
    Create the stealth_orders table if it doesn't exist.
    
    Main table for hidden order tracking with reveal conditions and execution state.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_orders (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID UNIQUE NOT NULL,
        parent_order_id UUID,
        product_id VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        
        total_size DECIMAL(16, 8) NOT NULL,
        revealed_size DECIMAL(16, 8) DEFAULT 0,
        remaining_size DECIMAL(16, 8) NOT NULL,
        executed_size DECIMAL(16, 8) DEFAULT 0,
        
        limit_price DECIMAL(16, 2) NOT NULL,
        
        status VARCHAR(32) NOT NULL DEFAULT 'HIDDEN',
        visibility_score FLOAT DEFAULT 0.0,
        
        reveal_condition_type VARCHAR(32) NOT NULL,
        reveal_condition_json JSONB NOT NULL,
        condition_first_met_at TIMESTAMP,
        condition_confirmed_at TIMESTAMP,
        
        sizing_strategy_json JSONB,
        
        revealed_orders JSONB DEFAULT '[]'::jsonb,
        last_placement_at TIMESTAMP,
        
        target_movement NUMERIC,
        target_movement_type VARCHAR(1),
        
        reason VARCHAR(255),
        notes TEXT
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("stealth_orders table done.")


def update_stealth_order_target_movement(stealth_order_id: str, target_movement: Optional[float], target_movement_type: str = "P") -> bool:
    """
    Update the target_movement and target_movement_type for a stealth order.
    
    Args:
        stealth_order_id: UUID of the stealth order
        target_movement: Profit target value (float) or None to clear
        target_movement_type: "P" for percentage (default) or "A" for absolute amount
    
    Returns:
        True if update successful, False otherwise
    
    Example:
        >>> update_stealth_order_target_movement(
        ...     stealth_order_id="550e8400-e29b-41d4-a716-446655440000",
        ...     target_movement=0.005,
        ...     target_movement_type="P"
        ... )
        True
    """
    try:
        query = """
        UPDATE stealth_orders
        SET target_movement = %s,
            target_movement_type = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE stealth_order_id = %s
        """
        
        rows_affected = DB_CLIENT.execute_update(
            query,
            (target_movement, target_movement_type if target_movement else None, stealth_order_id)
        )
        
        return rows_affected > 0
    except Exception as e:
        logger.error(f"✗ Error updating stealth order target_movement {stealth_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Update params - target_movement: {target_movement}, type: {target_movement_type}")
        return False


def get_stealth_order_by_id(stealth_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a stealth order by its ID.
    
    Args:
        stealth_order_id: UUID of the stealth order
    
    Returns:
        Dictionary with stealth order data or None if not found
    """
    try:
        query = """
        SELECT * FROM stealth_orders
        WHERE stealth_order_id = %s
        """
        
        results = DB_CLIENT.execute_query(query, (stealth_order_id,))
        return results[0] if results else None
    except Exception as e:
        logger.error(f"✗ Error fetching stealth order {stealth_order_id}: {type(e).__name__}: {e}")
        return None


def create_stealth_order_snapshots_table() -> None:
    """
    Create the stealth_order_snapshots table if it doesn't exist.
    
    Historical snapshots of stealth order state for auditing and analysis.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_snapshots (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID NOT NULL,
        status VARCHAR(32),
        revealed_size DECIMAL(16, 8),
        remaining_size DECIMAL(16, 8),
        executed_size DECIMAL(16, 8),
        condition_met BOOLEAN,
        condition_first_met_at TIMESTAMP,
        
        market_price DECIMAL(16, 2),
        market_bid DECIMAL(16, 2),
        market_ask DECIMAL(16, 2),
        market_spread DECIMAL(16, 2),
        market_volume_1m DECIMAL(16, 8),
        
        FOREIGN KEY (stealth_order_id) REFERENCES stealth_orders(stealth_order_id) ON DELETE CASCADE
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("stealth_order_snapshots table done.")


def create_stealth_order_reveal_history_table() -> None:
    """
    Create the stealth_order_reveal_history table if it doesn't exist.
    
    Detailed history of each reveal event with market conditions and trigger reasons.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_reveal_history (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID NOT NULL,
        reveal_number INT NOT NULL,
        revealed_size DECIMAL(16, 8) NOT NULL,
        placement_price DECIMAL(16, 2),
        placed_order_id UUID,
        
        market_price DECIMAL(16, 2),
        market_bid DECIMAL(16, 2),
        market_ask DECIMAL(16, 2),
        market_spread DECIMAL(16, 2),
        market_volume_1m DECIMAL(16, 8),
        
        reveal_trigger_reason VARCHAR(255),
        reveal_trigger_data JSONB,
        
        FOREIGN KEY (stealth_order_id) REFERENCES stealth_orders(stealth_order_id) ON DELETE CASCADE,
        UNIQUE (stealth_order_id, reveal_number)
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("stealth_order_reveal_history table done.")


def insert_order_parent(
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    target_movement: float,
    target_movement_type: str = "P",
    max_order_replacement: int = 0,
    current_order_replacement: int = 0,
    status: str = "pending"
) -> Optional[int]:
    """Insert a parent order into the order_parent table.
    
    Creates a new parent order entry with tracking for follow-up order replacement count.
    
    Args:
        client_order_id: Unique client-assigned order ID.
        product_id: Product ID (e.g., 'BTC-USDC').
        side: Order side ('BUY' or 'SELL').
        size: Order size/quantity.
        price: Order price.
        target_movement: Target profit/movement percentage.
        target_movement_type: Type of target ('P' for percentage, 'A' for absolute, default 'P').
        max_order_replacement: Maximum number of follow-up orders allowed (default 0).
        current_order_replacement: Current count of replacements created (default 0).
        status: Order status (default 'pending').
    
    Returns:
        The inserted order's database ID if successful, None if failed.
    
    Raises:
        Exception: If database insertion fails.
    """
    query = """
    INSERT INTO order_parent (
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
        target_movement,
        target_movement_type,
        max_order_replacement,
        current_order_replacement
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
        target_movement,
        target_movement_type,
        int(max_order_replacement),
        int(current_order_replacement),
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            logger.info(f"✓ Parent order inserted: {client_order_id} (DB ID: {inserted_id}, product: {product_id}, {side} {size} @ {price})")
            return inserted_id

        logger.warning(f"Failed to retrieve inserted order ID for: {client_order_id} - query executed but no result returned")
        return None
    except Exception as e:
        logger.error(f"✗ Error inserting parent order {client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Failed insert params - product: {product_id}, side: {side}, size: {size}, price: {price}, target_movement: {target_movement}")
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
    """Insert a child order into the order_child table.
    
    Creates a follow-up order that is linked to a parent order.
    
    Args:
        parent_client_order_id: The client_order_id of the parent order.
        client_order_id: Unique client-assigned ID for this child order.
        product_id: Product ID (e.g., 'BTC-USDC').
        side: Order side ('BUY' or 'SELL').
        size: Order size/quantity.
        price: Order price.
        status: Order status (default 'pending').
    
    Returns:
        The inserted order's database ID if successful, None if failed.
    
    Raises:
        Exception: If database insertion or FK constraint fails.
    """
    query = """
    INSERT INTO order_child (
        parent_client_order_id,
        client_order_id,
        product_id,
        side,
        size,
        price,
        status
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        parent_client_order_id,
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            logger.info(f"✓ Child order inserted: {client_order_id} (DB ID: {inserted_id}, parent: {parent_client_order_id}, {side} {size} @ {price})")
            return inserted_id

        logger.warning(f"Failed to retrieve inserted child order ID for: {client_order_id} - query executed but no result returned")
        return None
    except Exception as e:
        logger.error(f"✗ Error inserting child order {client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Failed insert params - parent: {parent_client_order_id}, product: {product_id}, side: {side}, size: {size}, price: {price}")
        return None


def insert_order_parent_batch(
    orders: List[Dict[str, Any]],
) -> List[Optional[int]]:
    """Insert multiple parent orders in batch.
    
    Processes a list of parent order dicts and inserts each one, returning
    the list of inserted IDs (None for failed entries).
    
    Args:
        orders: List of parent order dicts with keys: client_order_id, product_id,
                side, size, price, target_movement, and optional: target_movement_type,
                max_order_replacement, current_order_replacement, status.
    
    Returns:
        List of inserted database IDs, with None for any orders that failed validation
        or insertion.
    """
    inserted_ids: List[Optional[int]] = []
    
    logger.info(f"Starting batch insert of {len(orders)} parent orders")

    for idx, order in enumerate(orders, start=1):
        client_order_id = order.get("client_order_id")
        product_id = order.get("product_id")
        side = order.get("side")
        size = order.get("size")
        price = order.get("price")
        status = order.get("status", "pending")
        target_movement = order.get("target_movement")
        target_movement_type = order.get("target_movement_type", "P")
        max_order_replacement = int(order.get("max_order_replacement", 0))
        current_order_replacement = int(order.get("current_order_replacement", 0))

        if any(value is None for value in (
            client_order_id,
            product_id,
            side,
            size,
            price,
            target_movement,
        )):
            logger.warning(f"  [{idx}/{len(orders)}] Skipping invalid order - missing required fields: {order}")
            inserted_ids.append(None)
            continue

        result = insert_order_parent(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=size,
            price=price,
            target_movement=target_movement,
            target_movement_type=target_movement_type,
            max_order_replacement=max_order_replacement,
            current_order_replacement=current_order_replacement,
            status=status,
        )
        inserted_ids.append(result)

    success_count = sum(1 for x in inserted_ids if x is not None)
    logger.info(f"Batch insert complete: {success_count}/{len(orders)} parent orders inserted successfully")
    
    return inserted_ids


def insert_order_child_batch(
    orders: List[Dict[str, Any]]
) -> int:
    """Insert multiple child orders in batch.
    
    Processes a list of child order dicts and inserts each one, returning
    the total count of successfully inserted orders.
    
    Args:
        orders: List of child order dicts with keys: parent_client_order_id, client_order_id,
                product_id, side, size, price, and optional: status.
    
    Returns:
        Total count of successfully inserted child orders.
    """
    total_inserted: int = 0
    
    logger.info(f"Starting batch insert of {len(orders)} child orders")

    for idx, order in enumerate(orders, start=1):
        parent_client_order_id = order.get("parent_client_order_id")
        client_order_id = order.get("client_order_id")
        product_id = order.get("product_id")
        side = order.get("side")
        size = order.get("size")
        price = order.get("price")
        status = order.get("status", "pending")

        if any(value is None for value in (
            parent_client_order_id,
            client_order_id,
            product_id,
            side,
            size,
            price,
        )):
            logger.warning(f"  [{idx}/{len(orders)}] Skipping invalid child order - missing required fields: {order}")
            continue

        result = insert_order_child(
            parent_client_order_id=parent_client_order_id,
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=size,
            price=price,
            status=status,
        )
        if result is not None:
            total_inserted += 1

    logger.info(f"Batch insert complete: {total_inserted}/{len(orders)} child orders inserted successfully")
    
    return total_inserted
    """Retrieve a parent order by client_order_id.
    
    Args:
        client_order_id: The client-specified parent order ID.
    
    Returns:
        Parent order dict if found, None if not found.
    """
    query = "SELECT * FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return results[0] if results else None


def get_parent_orders() -> List[Dict[str, Any]]:
    """Retrieve all parent orders from the database.
    
    Args:
        None
    
    Returns:
        List of all parent order dicts, or empty list if none exist.
    """
    query = "SELECT * FROM order_parent"
    return DB_CLIENT.execute_query(query)


def get_parent_order(client_order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single parent order by client_order_id.
    
    Args:
        client_order_id: The client_order_id to look up.
    
    Returns:
        Parent order dict if found, None otherwise.
    """
    query = "SELECT * FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return results[0] if results else None


def get_child_orders(parent_client_order_id: str) -> List[Dict[str, Any]]:
    """Retrieve all child orders for a parent order.
    
    Args:
        parent_client_order_id: The client_order_id of the parent order.
    
    Returns:
        List of child order dicts for the parent, or empty list if none exist.
    """
    query = "SELECT * FROM order_child WHERE parent_client_order_id = %s"
    return DB_CLIENT.execute_query(query, (parent_client_order_id,))


def child_order_exists(
    parent_client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
) -> bool:
    """Check if a child order already exists matching the template.
    
    Prevents duplicate child orders by checking for exact matches on all key fields.
    
    Args:
        parent_client_order_id: The parent order's client_order_id.
        product_id: Product ID to match.
        side: Order side ('BUY' or 'SELL') to match.
        size: Order size to match.
        price: Order price to match.
    
    Returns:
        True if a matching child order exists, False otherwise.
    """
    query = """
    SELECT 1
    FROM order_child
    WHERE parent_client_order_id = %s
      AND product_id = %s
      AND side = %s
      AND size = %s
      AND price = %s
    LIMIT 1
    """
    params = (
        parent_client_order_id,
        product_id,
        side,
        size,
        price,
    )
    results = DB_CLIENT.execute_query(query, params)
    return bool(results)


def get_order_parent_replacement_count(client_order_id: str) -> Optional[int]:
    """Retrieve the current replacement count for a parent order.
    
    Args:
        client_order_id: The client-specified parent order ID.
    
    Returns:
        The current replacement count, or None if parent not found.
    """
    query = "SELECT current_order_replacement FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return int(results[0]["current_order_replacement"]) if results else None


def update_order_parent_status(
    client_order_id: str,
    status: str
) -> int:
    """Update the status of a parent order.
    
    Args:
        client_order_id: The client-specified parent order ID.
        status: New status value.
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = "UPDATE order_parent SET status = %s WHERE client_order_id = %s"
    params = (status, client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        logger.info(f"Parent order status updated: {client_order_id} -> {status}")
    else:
        logger.warning(f"No parent order found to update status: {client_order_id}")
    return result


def update_order_parent_replacement_count(
    client_order_id: str,
    current_order_replacement: int
) -> int:
    """Update the current replacement count for a parent order.
    
    Args:
        client_order_id: The client-specified parent order ID.
        current_order_replacement: New replacement count value.
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE order_parent
    SET current_order_replacement = %s
    WHERE client_order_id = %s
    """
    params = (int(current_order_replacement), client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        logger.info(
            f"Parent order replacement count updated: "
            f"{client_order_id} -> {current_order_replacement}"
        )
    else:
        logger.warning(f"No parent order found to update replacement count: {client_order_id}")
    return result


def increment_order_parent_replacement_count(client_order_id: str) -> Optional[int]:
    """Increment the current replacement count for a parent order.
    
    Adds 1 to the existing replacement count in a single atomic operation.
    
    Args:
        client_order_id: The client-specified parent order ID.
    
    Returns:
        The new replacement count after incrementing, or None if parent not found.
    """
    query = """
    UPDATE order_parent
    SET current_order_replacement = current_order_replacement + 1
    WHERE client_order_id = %s
    RETURNING current_order_replacement
    """
    results = DB_CLIENT.execute_query(query, (client_order_id,))

    if results:
        new_count = int(results[0]["current_order_replacement"])
        logger.info(f"Parent order replacement count incremented: {client_order_id} -> {new_count}")
        return new_count

    logger.warning(f"No parent order found to increment replacement count: {client_order_id}")
    return None


def update_order_parent_replacement_config(
    client_order_id: str,
    max_order_replacement: int,
    current_order_replacement: Optional[int] = None,
) -> int:
    """Update replacement configuration for a parent order.
    
    Updates max and/or current replacement counts. If current_order_replacement
    is None, only updates max. If provided, updates both.
    
    Args:
        client_order_id: The client-specified parent order ID.
        max_order_replacement: New maximum replacement count.
        current_order_replacement: Optional new current replacement count (default None).
    
    Returns:
        Number of rows updated (0 or 1).
    """
    if current_order_replacement is None:
        query = """
        UPDATE order_parent
        SET max_order_replacement = %s
        WHERE client_order_id = %s
        """
        params = (int(max_order_replacement), client_order_id)
    else:
        query = """
        UPDATE order_parent
        SET max_order_replacement = %s,
            current_order_replacement = %s
        WHERE client_order_id = %s
        """
        params = (
            int(max_order_replacement),
            int(current_order_replacement),
            client_order_id,
        )

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(
            f"Parent order replacement config updated: {client_order_id} "
            f"-> max={int(max_order_replacement)}"
            + (
                f", current={int(current_order_replacement)}"
                if current_order_replacement is not None else ""
            )
        )
    else:
        logger.warning(f"No parent order found to update replacement config: {client_order_id}")
    return result


def update_order_parent_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """Update status for multiple parent orders in batch.
    
    Processes a list of status updates and applies each one.
    
    Args:
        status_updates: List of dicts with 'client_order_id' and 'status' keys.
    
    Returns:
        Total count of rows successfully updated.
    """
    total_updated: int = 0

    for update in status_updates:
        client_order_id = update.get("client_order_id")
        status = update.get("status")

        if not all([client_order_id, status]):
            logger.warning(f"Skipping invalid parent order status update: {update}")
            continue

        result = update_order_parent_status(client_order_id, status)
        total_updated += result

    return total_updated


def update_order_child_status(
    client_order_id: str,
    status: str
) -> int:
    """Update the status of a child order.
    
    Args:
        client_order_id: The client-specified child order ID.
        status: New status value.
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = "UPDATE order_child SET status = %s WHERE client_order_id = %s"
    params = (status, client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        logger.info(f"Child order status updated: {client_order_id} -> {status}")
    else:
        logger.warning(f"No child order found to update status: {client_order_id}")
    return result


def update_order_child_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """Update status for multiple child orders in batch.
    
    Processes a list of status updates and applies each one.
    
    Args:
        status_updates: List of dicts with 'client_order_id' and 'status' keys.
    
    Returns:
        Total count of rows successfully updated.
    """
    total_updated: int = 0

    for update in status_updates:
        client_order_id = update.get("client_order_id")
        status = update.get("status")

        if not all([client_order_id, status]):
            logger.warning(f"Skipping invalid child order status update: {update}")
            continue

        result = update_order_child_status(client_order_id, status)
        total_updated += result

    return total_updated


def adopt_child_to_parent(
    child_client_order_id: str,
    new_parent_client_order_id: str,
    keep_adoption_history: bool = True
) -> bool:
    """
    Reassign a child order to a new parent order (adoption).
    
    Updates the parent-child relationship in the database. Optionally tracks
    the original parent for audit history.
    
    Args:
        child_client_order_id: The UUID of the child order to adopt.
        new_parent_client_order_id: The UUID of the new parent order.
        keep_adoption_history: If True, stores the old parent in previous_parent_client_order_id
                               and timestamp in adopted_at. If False, old parent is lost.
    
    Returns:
        True if adoption was successful, False otherwise.
    
    Raises:
        Exception: If database update fails.
    
    Examples:
        >>> # Adopt child to new parent, keeping history
        >>> result = adopt_child_to_parent(
        ...     child_client_order_id="child-uuid-123",
        ...     new_parent_client_order_id="parent-uuid-456",
        ...     keep_adoption_history=True
        ... )
        >>> if result:
        ...     print("Child adopted successfully")
        
        >>> # Adopt without keeping history
        >>> result = adopt_child_to_parent(
        ...     child_client_order_id="child-uuid-123",
        ...     new_parent_client_order_id="parent-uuid-456",
        ...     keep_adoption_history=False
        ... )
    
    Notes:
        - Validates that both parent and child exist before updating
        - When keep_adoption_history=True, stores old parent ID for audit trail
        - The timestamp adopted_at records when the adoption occurred
        - Old parent-child relationship is broken by updating the FK
    """
    # First, validate that child exists
    validate_child_query = (
        "SELECT parent_client_order_id FROM order_child WHERE client_order_id = %s"
    )
    try:
        child_result = DB_CLIENT.execute_query(validate_child_query, (child_client_order_id,))
        if not child_result:
            logger.error(f"Adoption failed: Child order not found: {child_client_order_id}")
            return False
        
        old_parent = child_result[0].get("parent_client_order_id")
    except Exception as e:
        logger.error(f"Error validating child order {child_client_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Validate that new parent exists
    validate_parent_query = (
        "SELECT client_order_id FROM order_parent WHERE client_order_id = %s"
    )
    try:
        parent_result = DB_CLIENT.execute_query(validate_parent_query, (new_parent_client_order_id,))
        if not parent_result:
            logger.error(f"Adoption failed: Parent order not found: {new_parent_client_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error validating parent order {new_parent_client_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Perform the adoption
    if keep_adoption_history:
        # Preserve old parent and add adoption timestamp
        update_query = """
        UPDATE order_child 
        SET parent_client_order_id = %s,
            previous_parent_client_order_id = %s,
            adopted_at = CURRENT_TIMESTAMP
        WHERE client_order_id = %s
        """
        params = (new_parent_client_order_id, old_parent, child_client_order_id)
    else:
        # Just update the parent, no history
        update_query = """
        UPDATE order_child 
        SET parent_client_order_id = %s
        WHERE client_order_id = %s
        """
        params = (new_parent_client_order_id, child_client_order_id)
    
    try:
        result = DB_CLIENT.execute_update(update_query, params)
        if result > 0:
            history_note = (
                f" (previous parent: {old_parent})"
                if keep_adoption_history else ""
            )
            logger.info(
                f"✓ Child order adopted: {child_client_order_id} "
                f"{old_parent} → {new_parent_client_order_id}{history_note}"
            )
            return True
        else:
            logger.error(f"✗ Adoption failed: No child order found: {child_client_order_id}")
            return False
    except Exception as e:
        logger.error(f"✗ Error adopting child order {child_client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Adoption details - new_parent: {new_parent_client_order_id}, keep_history: {keep_adoption_history}")
        return False


def find_compatible_parents(
    child_order: Dict[str, Any],
    parent_orders: List[Dict[str, Any]],
    price_tolerance_pct: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find parent orders compatible for adopting a child order.
    
    Compatibility criteria:
    - Same product_id
    - Same side
    - Price difference < price_tolerance_pct% of parent price
    
    Args:
        child_order: Child order dict with product_id, side, price keys.
        parent_orders: List of parent order dicts to search.
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
    
    Returns:
        List of compatible parent orders, sorted by price difference (closest first).
    """
    compatible = []
    child_product = child_order.get("product_id")
    child_side = child_order.get("side")
    child_price = float(child_order.get("price", 0))
    
    for parent in parent_orders:
        parent_product = parent.get("product_id")
        parent_side = parent.get("side")
        parent_price = float(parent.get("price", 0))
        
        # Check product and side match
        if parent_product != child_product or parent_side != child_side:
            continue
        
        # Skip if parent price is invalid
        if parent_price <= 0:
            continue
        
        # Check price difference
        price_diff_pct = abs(child_price - parent_price) / parent_price * 100
        if price_diff_pct < price_tolerance_pct:
            compatible.append({
                "parent": parent,
                "price_diff_pct": price_diff_pct
            })
    
    # Sort by price difference (closest first)
    compatible.sort(key=lambda x: x["price_diff_pct"])
    return compatible


def adopt_orphaned_orders(
    price_tolerance_pct: float = 0.5,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Find and adopt orphaned child orders to compatible parents.
    
    Searches for child orders without a matching parent and attempts to find
    compatible parents based on product_id, side, and price similarity.
    
    Args:
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
        dry_run: If True, only report what would be adopted without making changes.
    
    Returns:
        Dict with adoption results:
        {
            "total_children": int,
            "orphaned_found": int,
            "adoptions_completed": int,
            "adoptions_skipped": int,
            "details": List[Dict with adoption details]
        }
    
    Examples:
        >>> # Find and adopt orphaned orders
        >>> result = adopt_orphaned_orders(price_tolerance_pct=0.5)
        >>> print(f"Adopted {result['adoptions_completed']} orders")
        
        >>> # Dry run to see what would be adopted
        >>> result = adopt_orphaned_orders(dry_run=True)
        >>> for detail in result['details']:
        ...     print(f"Would adopt {detail['child_id']} to {detail['parent_id']}")
    """
    try:
        # Get all parents and children
        all_parents = get_parent_orders()
        all_children = []
        orphaned_children = []
        
        # Collect all children and find orphaned ones
        if all_parents:
            all_parent_ids = {p["client_order_id"] for p in all_parents}
            
            for parent in all_parents:
                children = get_child_orders(parent["client_order_id"])
                all_children.extend(children)
        else:
            all_parent_ids = set()
        
        # Find orphaned children (parent doesn't exist)
        for child in all_children:
            if child.get("parent_client_order_id") not in all_parent_ids:
                orphaned_children.append(child)
        
        result = {
            "total_children": len(all_children),
            "orphaned_found": len(orphaned_children),
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": []
        }
        
        if not orphaned_children:
            print(f"✅ No orphaned children found")
            return result
        
        print(f"\n📍 Found {len(orphaned_children)} orphaned child orders")
        print(f"   Searching for compatible parents (tolerance: {price_tolerance_pct}%)...")
        
        # Try to adopt each orphaned child
        for orphan in orphaned_children:
            # Find compatible parents
            compatible = find_compatible_parents(
                orphan,
                all_parents,
                price_tolerance_pct=price_tolerance_pct
            )
            
            if not compatible:
                result["adoptions_skipped"] += 1
                result["details"].append({
                    "child_id": orphan.get("client_order_id"),
                    "status": "SKIPPED_NO_COMPATIBLE_PARENT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "price": orphan.get("price"),
                    "reason": f"No compatible parents found (tolerance: {price_tolerance_pct}%)"
                })
                continue
            
            # Adopt to the closest parent
            best_parent = compatible[0]["parent"]
            parent_id = best_parent.get("client_order_id")
            price_diff = compatible[0]["price_diff_pct"]
            
            if dry_run:
                result["adoptions_completed"] += 1
                result["details"].append({
                    "child_id": orphan.get("client_order_id"),
                    "status": "DRY_RUN_WOULD_ADOPT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "child_price": orphan.get("price"),
                    "parent_id": parent_id,
                    "parent_price": best_parent.get("price"),
                    "price_diff_pct": price_diff
                })
            else:
                success = adopt_child_to_parent(
                    child_client_order_id=orphan.get("client_order_id"),
                    new_parent_client_order_id=parent_id,
                    keep_adoption_history=True
                )
                
                if success:
                    result["adoptions_completed"] += 1
                    result["details"].append({
                        "child_id": orphan.get("client_order_id"),
                        "status": "ADOPTED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "child_price": orphan.get("price"),
                        "parent_id": parent_id,
                        "parent_price": best_parent.get("price"),
                        "price_diff_pct": price_diff
                    })
                else:
                    result["adoptions_skipped"] += 1
                    result["details"].append({
                        "child_id": orphan.get("client_order_id"),
                        "status": "ADOPTION_FAILED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "parent_id": parent_id,
                        "reason": "Database adoption failed - check logs"
                    })
        
        # Print summary
        mode = "[DRY RUN] " if dry_run else ""
        print(f"\n✅ {mode}Adoption Summary:")
        print(f"   Total children: {result['total_children']}")
        print(f"   Orphaned found: {result['orphaned_found']}")
        print(f"   Adoptions completed: {result['adoptions_completed']}")
        print(f"   Adoptions skipped: {result['adoptions_skipped']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error during adoption process: {e}")
        return {
            "total_children": 0,
            "orphaned_found": 0,
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": [],
            "error": str(e)
        }


def find_compatible_stealth_parents(
    orphaned_stealth: Dict[str, Any],
    all_parent_orders: List[Dict[str, Any]],
    price_tolerance_pct: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find parent orders compatible for adopting an orphaned stealth order.
    
    Compatibility criteria:
    - Same product_id
    - Same side
    - Price difference < price_tolerance_pct% of parent price
    
    Args:
        orphaned_stealth: Orphaned stealth order dict with product_id, side, limit_price keys.
        all_parent_orders: List of parent order dicts from order_parent table to search.
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
    
    Returns:
        List of compatible parent orders, sorted by price difference (closest first).
    """
    compatible = []
    child_product = orphaned_stealth.get("product_id")
    child_side = orphaned_stealth.get("side")
    child_price = float(orphaned_stealth.get("limit_price", 0))
    
    for parent in all_parent_orders:
        parent_product = parent.get("product_id")
        parent_side = parent.get("side")
        parent_price = float(parent.get("price", 0))
        
        # Check product and side match
        if parent_product != child_product or parent_side != child_side:
            continue
        
        # Skip if parent price is invalid
        if parent_price <= 0:
            continue
        
        # Check price difference
        price_diff_pct = abs(child_price - parent_price) / parent_price * 100
        if price_diff_pct <= price_tolerance_pct:
            compatible.append({
                "parent": parent,
                "price_diff_pct": price_diff_pct
            })
    
    # Sort by price difference (closest first)
    compatible.sort(key=lambda x: x["price_diff_pct"])
    return compatible


def adopt_stealth_order_to_parent(
    stealth_order_id: str,
    new_parent_order_id: str
) -> bool:
    """
    Reassign a stealth order to a new parent order (adoption).
    
    Updates the parent reference in the stealth_orders table to a valid order_parent.
    
    Args:
        stealth_order_id: The UUID of the stealth order to adopt.
        new_parent_order_id: The UUID of the new parent order (client_order_id from order_parent).
    
    Returns:
        True if adoption was successful, False otherwise.
    """
    # First, validate that stealth order exists
    validate_stealth_query = (
        "SELECT parent_order_id FROM stealth_orders WHERE stealth_order_id = %s"
    )
    try:
        stealth_result = DB_CLIENT.execute_query(validate_stealth_query, (stealth_order_id,))
        if not stealth_result:
            logger.error(f"Adoption failed: Stealth order not found: {stealth_order_id}")
            return False
        
        old_parent = stealth_result[0].get("parent_order_id")
    except Exception as e:
        logger.error(f"Error validating stealth order {stealth_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Validate that new parent exists in order_parent table
    validate_parent_query = (
        "SELECT client_order_id FROM order_parent WHERE client_order_id = %s"
    )
    try:
        parent_result = DB_CLIENT.execute_query(validate_parent_query, (new_parent_order_id,))
        if not parent_result:
            logger.error(f"Adoption failed: Parent order not found: {new_parent_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error validating parent order {new_parent_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Perform the adoption
    update_query = """
    UPDATE stealth_orders
    SET parent_order_id = %s,
        updated_at = CURRENT_TIMESTAMP
    WHERE stealth_order_id = %s
    """
    params = (new_parent_order_id, stealth_order_id)
    
    try:
        result = DB_CLIENT.execute_update(update_query, params)
        if result > 0:
            logger.info(
                f"Stealth order adopted: {stealth_order_id} "
                f"from {old_parent} -> {new_parent_order_id}"
            )
            return True
        else:
            logger.error(f"Adoption failed: No stealth order found: {stealth_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error adopting stealth order {stealth_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Adoption details - new_parent: {new_parent_order_id}")
        return False


def adopt_orphaned_stealth_orders(
    price_tolerance_pct: float = 0.5,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Find and adopt orphaned stealth orders to compatible stealth parents.
    
    Searches for stealth orders without a matching parent and attempts to find
    compatible stealth parents based on product_id, side, and price similarity.
    
    Args:
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
        dry_run: If True, only report what would be adopted without making changes.
    
    Returns:
        Dict with adoption results:
        {
            "total_stealth_orders": int,
            "orphaned_found": int,
            "stealth_parents": int,
            "adoptions_completed": int,
            "adoptions_skipped": int,
            "details": List[Dict with adoption details]
        }
    
    Examples:
        >>> # Find and adopt orphaned stealth orders
        >>> result = adopt_orphaned_stealth_orders(price_tolerance_pct=0.5)
        >>> print(f"Adopted {result['adoptions_completed']} stealth orders")
        
        >>> # Dry run to see what would be adopted
        >>> result = adopt_orphaned_stealth_orders(dry_run=True)
        >>> for detail in result['details']:
        ...     print(f"Would adopt {detail['stealth_id']} to {detail['parent_id']}")
    """
    try:
        # Get all orphaned stealth orders (those with parent_order_id NULL)
        orphaned_query = (
            "SELECT * FROM stealth_orders WHERE parent_order_id IS NULL ORDER BY created_at DESC"
        )
        orphaned_stealth = DB_CLIENT.execute_query(orphaned_query)
        
        # Get all parent orders from order_parent table
        parents_query = (
            "SELECT client_order_id, product_id, side, price FROM order_parent ORDER BY created_at DESC"
        )
        all_parent_orders = DB_CLIENT.execute_query(parents_query)
        
        # Count total stealth orders
        total_stealth_query = "SELECT COUNT(*) as count FROM stealth_orders"
        total_stealth_result = DB_CLIENT.execute_query(total_stealth_query)
        total_stealth_count = total_stealth_result[0]["count"] if total_stealth_result else 0
        
        result = {
            "total_stealth_orders": total_stealth_count,
            "orphaned_found": len(orphaned_stealth),
            "parent_orders_available": len(all_parent_orders),
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": []
        }
        
        if not orphaned_stealth:
            print(f"✅ No orphaned stealth orders found")
            return result
        
        print(f"\n📍 Found {len(orphaned_stealth)} orphaned stealth orders")
        print(f"   Found {len(all_parent_orders)} parent orders")
        print(f"   Searching for compatible parents (tolerance: {price_tolerance_pct}%)...")
        
        # Try to adopt each orphaned stealth order
        for orphan in orphaned_stealth:
            # Find compatible parent orders
            compatible = find_compatible_stealth_parents(
                orphan,
                all_parent_orders,
                price_tolerance_pct=price_tolerance_pct
            )
            
            if not compatible:
                result["adoptions_skipped"] += 1
                result["details"].append({
                    "stealth_id": orphan.get("stealth_order_id"),
                    "status": "SKIPPED_NO_COMPATIBLE_PARENT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "price": orphan.get("limit_price"),
                    "reason": f"No compatible stealth parents found (tolerance: {price_tolerance_pct}%)"
                })
                continue
            
            # Adopt to the closest parent
            best_parent = compatible[0]["parent"]
            parent_id = best_parent.get("client_order_id")
            price_diff = compatible[0]["price_diff_pct"]
            
            if dry_run:
                result["adoptions_completed"] += 1
                result["details"].append({
                    "stealth_id": orphan.get("stealth_order_id"),
                    "status": "DRY_RUN_WOULD_ADOPT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "child_price": orphan.get("limit_price"),
                    "parent_id": parent_id,
                    "parent_price": best_parent.get("price"),
                    "price_diff_pct": price_diff
                })
            else:
                success = adopt_stealth_order_to_parent(
                    stealth_order_id=orphan.get("stealth_order_id"),
                    new_parent_order_id=parent_id
                )
                
                if success:
                    result["adoptions_completed"] += 1
                    result["details"].append({
                        "stealth_id": orphan.get("stealth_order_id"),
                        "status": "ADOPTED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "child_price": orphan.get("limit_price"),
                        "parent_id": parent_id,
                        "parent_price": best_parent.get("price"),
                        "price_diff_pct": price_diff
                    })
                else:
                    result["adoptions_skipped"] += 1
                    result["details"].append({
                        "stealth_id": orphan.get("stealth_order_id"),
                        "status": "ADOPTION_FAILED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "parent_id": parent_id,
                        "reason": "Database adoption failed - check logs"
                    })
        
        # Print summary
        mode = "[DRY RUN] " if dry_run else ""
        print(f"\n✅ {mode}Stealth Adoption Summary:")
        print(f"   Total stealth orders: {result['total_stealth_orders']}")
        print(f"   Orphaned found: {result['orphaned_found']}")
        print(f"   Parent orders available: {result['parent_orders_available']}")
        print(f"   Adoptions completed: {result['adoptions_completed']}")
        print(f"   Adoptions skipped: {result['adoptions_skipped']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error during stealth adoption process: {e}")
        return {
            "total_stealth_orders": 0,
            "orphaned_found": 0,
            "parent_orders_available": 0,
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": [],
            "error": str(e)
        }

def clear_all_stealth_orders() -> Dict[str, Any]:
    """
    Clears all stealth orders from the database.
    
    Deletes all records from the stealth_orders table. Due to cascading delete
    constraints, related records in stealth_order_snapshots and 
    stealth_order_reveal_history tables are automatically deleted.
    
    Returns:
        Dict with clear operation result:
        {
            "success": bool,
            "rows_deleted": int,
            "message": str,
            "error": str (if operation failed)
        }
    
    Examples:
        >>> # Clear all stealth orders
        >>> result = clear_all_stealth_orders()
        >>> if result["success"]:
        ...     print(f"Cleared {result['rows_deleted']} stealth orders")
        >>> else:
        ...     print(f"Error: {result['error']}")
    """
    try:
        # Get count before deletion for reporting
        count_query = "SELECT COUNT(*) as count FROM stealth_orders"
        count_result = DB_CLIENT.execute_query(count_query)
        count_before = count_result[0]["count"] if count_result else 0
        
        # Execute DELETE query for all stealth orders
        delete_query = "DELETE FROM stealth_orders"
        rows_deleted = DB_CLIENT.execute_update(delete_query)
        
        result = {
            "success": True,
            "rows_deleted": rows_deleted,
            "message": f"Successfully cleared {rows_deleted} stealth orders"
        }
        
        print(f"? {result['message']}")
        if count_before > 0:
            print(f"   (Cascaded: snapshots and reveal history also deleted)")
        
        return result
        
    except Exception as e:
        error_msg = f"Failed to clear stealth orders: {str(e)}"
        print(f"? {error_msg}")
        return {
            "success": False,
            "rows_deleted": 0,
            "error": error_msg
        }


def create_order_moves_table() -> None:
    """
    Create the order_moves table to track when cancelled orders are "moved" to new replacement orders.
    
    An order "move" occurs when a cancelled order is replaced with a new order that takes
    its place as the parent order, rather than becoming a child order. This tracks the
    relationship between the cancelled order and its replacement.
    
    Table columns:
    - id: Unique identifier for the move record
    - original_parent_client_order_id: The client_order_id of the cancelled parent order
    - new_parent_client_order_id: The client_order_id of the new replacement parent order (NULL if pre-marked)
    - move_on_cancel: If True, execute move automatically when order cancels (for automation)
    - moved_at: Timestamp when the move occurred (NULL until actual move happens)
    - reason: Optional reason for the move (e.g., "user_move", "auto_move")
    - notes: Optional additional details about the move
    - created_at: Timestamp when the move record was created
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_moves (
        id SERIAL PRIMARY KEY,
        original_parent_client_order_id VARCHAR(40) NOT NULL,
        new_parent_client_order_id VARCHAR(40),
        move_on_cancel BOOLEAN DEFAULT FALSE,
        moved_at TIMESTAMP,
        reason VARCHAR(50) DEFAULT 'auto_move',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (original_parent_client_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE,
        FOREIGN KEY (new_parent_client_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_moves table done.")


def insert_order_move(
    original_parent_client_order_id: str,
    new_parent_client_order_id: str = None,
    reason: str = "auto_move",
    notes: str = None,
    move_on_cancel: bool = False
) -> Optional[int]:
    """
    Record a move when a cancelled parent order is replaced with a new parent order.
    
    Can be used in two ways:
    1. Record completed move: new_parent_client_order_id is set, moved_at is set
    2. Pre-mark for automation: new_parent_client_order_id is None, move_on_cancel=True
       (will be set when order cancels)
    
    Args:
        original_parent_client_order_id: The client_order_id of the cancelled parent order.
        new_parent_client_order_id: The client_order_id of the new replacement parent order.
                                  If None, this is a pre-marked move.
        reason: Reason for the move (default 'auto_move'). Other values: 'user_move', etc.
        notes: Optional additional details about the move.
        move_on_cancel: If True, execute move automatically when order cancels (for automation).
    
    Returns:
        The inserted move record's database ID if successful, None if failed.
    
    Raises:
        Exception: If database insertion fails.
        
    Example - Completed move:
        >>> move_id = insert_order_move(
        ...     original_parent_client_order_id="old_parent_uuid",
        ...     new_parent_client_order_id="new_parent_uuid",
        ...     reason="cancelled_order_moved",
        ...     notes="Cancelled due to user request"
        ... )
    
    Example - Pre-marked move (for automation):
        >>> move_id = insert_order_move(
        ...     original_parent_client_order_id="parent_uuid",
        ...     reason="auto_move_scheduled",
        ...     notes="Will move to strategy B if cancelled",
        ...     move_on_cancel=True
        ... )
    """
    query = """
    INSERT INTO order_moves (
        original_parent_client_order_id,
        new_parent_client_order_id,
        reason,
        notes,
        move_on_cancel,
        moved_at
    )
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        original_parent_client_order_id,
        new_parent_client_order_id,
        reason,
        notes,
        move_on_cancel,
        get_local_now() if new_parent_client_order_id else None  # Only set if completed move
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            if new_parent_client_order_id:
                logger.info(
                    f"✓ Order move recorded: {original_parent_client_order_id} "
                    f"→ {new_parent_client_order_id} (DB ID: {inserted_id}, reason: {reason})"
                )
            else:
                logger.info(
                    f"✓ Order move pre-marked: {original_parent_client_order_id} "
                    f"(DB ID: {inserted_id}, move_on_cancel={move_on_cancel}, reason: {reason})"
                )
            return inserted_id

        logger.warning(f"Failed to retrieve inserted move record ID for: {original_parent_client_order_id}")
        return None
    except Exception as e:
        logger.error(f"✗ Error inserting order move ({original_parent_client_order_id}): {type(e).__name__}: {e}")
        logger.debug(f"  Move details - new_parent: {new_parent_client_order_id}, reason: {reason}, move_on_cancel: {move_on_cancel}")
        return None


def get_order_move(original_parent_client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a move record by the original parent order ID.
    
    Args:
        original_parent_client_order_id: The client_order_id of the original (cancelled) parent order.
    
    Returns:
        Move record dict if found, None if not found.
        
    Example:
        >>> move = get_order_move("old_parent_uuid")
        >>> if move:
        ...     print(f"Order was moved to: {move['new_parent_client_order_id']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s
    ORDER BY moved_at DESC
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (original_parent_client_order_id,))
    return results[0] if results else None


def get_order_moves_by_original_parent(original_parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all move records for a given original parent order ID.
    
    Useful for tracking the full history of moves for a parent order.
    
    Args:
        original_parent_client_order_id: The client_order_id of the original parent order.
    
    Returns:
        List of move record dicts, ordered by moved_at timestamp (newest first).
        
    Example:
        >>> moves = get_order_moves_by_original_parent("old_parent_uuid")
        >>> for move in moves:
        ...     print(f"Moved to {move['new_parent_client_order_id']} on {move['moved_at']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s
    ORDER BY moved_at DESC
    """
    return DB_CLIENT.execute_query(query, (original_parent_client_order_id,))


def get_order_moves_by_new_parent(new_parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all move records where a given order ID is the new parent.
    
    Useful for finding all orders that resulted from a move.
    
    Args:
        new_parent_client_order_id: The client_order_id of the new parent order.
    
    Returns:
        List of move record dicts, ordered by moved_at timestamp (newest first).
        
    Example:
        >>> moves = get_order_moves_by_new_parent("new_parent_uuid")
        >>> for move in moves:
        ...     print(f"Replaced {move['original_parent_client_order_id']} on {move['moved_at']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE new_parent_client_order_id = %s
    ORDER BY moved_at DESC
    """
    return DB_CLIENT.execute_query(query, (new_parent_client_order_id,))


def has_order_moved(client_order_id: str) -> bool:
    """
    Check if an order has been moved (replaced).
    
    Args:
        client_order_id: The client_order_id to check (could be original or new parent).
    
    Returns:
        True if the order was involved in a move (either as original or new parent), False otherwise.
        
    Example:
        >>> if has_order_moved("parent_uuid"):
        ...     print("This order has been moved or is a replacement")
    """
    query = """
    SELECT 1 FROM order_moves 
    WHERE original_parent_client_order_id = %s 
       OR new_parent_client_order_id = %s
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (client_order_id, client_order_id))
    return bool(results)


def get_pending_move(original_parent_client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a pre-marked (pending) move for an order that hasn't been executed yet.
    
    Pre-marked moves have:
    - move_on_cancel = True (should execute automatically on cancel)
    - new_parent_client_order_id = None (not yet set)
    - moved_at = NULL (not yet executed)
    
    Args:
        original_parent_client_order_id: The client_order_id of the parent to check.
    
    Returns:
        Pending move record dict if found, None if no pending move.
        
    Example:
        >>> pending = get_pending_move("parent_uuid")
        >>> if pending:
        ...     print(f"This order is pre-marked for move: {pending['reason']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s 
      AND move_on_cancel = TRUE
      AND new_parent_client_order_id IS NULL
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (original_parent_client_order_id,))
    return results[0] if results else None


def has_pending_move(original_parent_client_order_id: str) -> bool:
    """
    Check if an order has a pre-marked move waiting to be executed on cancel.
    
    Args:
        original_parent_client_order_id: The client_order_id of the parent to check.
    
    Returns:
        True if a pending move exists, False otherwise.
        
    Example:
        >>> if has_pending_move("parent_uuid"):
        ...     print("Order is pre-marked for automatic move on cancel")
    """
    return get_pending_move(original_parent_client_order_id) is not None


def create_pending_move(
    original_parent_client_order_id: str,
    new_order_details: Dict[str, Any],
    reason: str = "auto_move_scheduled",
    notes: str = None
) -> Optional[int]:
    """
    Pre-mark an order for automatic move when it cancels.
    
    Creates a move record with move_on_cancel=True and no new parent yet.
    When the order cancels, the new parent will be created and move executed.
    
    Args:
        original_parent_client_order_id: The client_order_id to pre-mark.
        new_order_details: Dict with new parent configuration (same as move_order):
            - product_id, side, size, price, target_movement, target_movement_type, max_order_replacement
        reason: Reason for the pending move (default 'auto_move_scheduled').
        notes: Optional additional context.
    
    Returns:
        The move record ID if successful, None if failed.
        
    Example:
        >>> move_id = create_pending_move(
        ...     original_parent_client_order_id="parent_uuid",
        ...     new_order_details={
        ...         "product_id": "BTC-USDC",
        ...         "side": "SELL",
        ...         "size": 0.5,
        ...         "price": 43000.0,
        ...         "target_movement": 0.01,
        ...         "max_order_replacement": 5
        ...     },
        ...     reason="scheduled_reversal",
        ...     notes="Switch to sell if cancelled after 1 hour"
        ... )
        >>> if move_id:
        ...     print(f"Pending move created: {move_id}")
    """
    # Store the new order details as JSON in notes if not provided
    import json
    if notes is None:
        notes = f"Pending move config: {json.dumps(new_order_details)}"
    else:
        notes = f"{notes}\n\nPending move config: {json.dumps(new_order_details)}"
    
    query = """
    INSERT INTO order_moves (
        original_parent_client_order_id,
        move_on_cancel,
        reason,
        notes
    )
    VALUES (%s, %s, %s, %s)
    RETURNING id
    """
    params = (original_parent_client_order_id, True, reason, notes)
    
    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            move_id = results[0]["id"]
            logger.info(
                f"Pending move created: {original_parent_client_order_id} "
                f"(DB ID: {move_id}, reason: {reason})"
            )
            return move_id
        return None
    except Exception as e:
        logger.error(f"Error creating pending move {original_parent_client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Move details - new_parent: {new_parent_client_order_id}, reason: {reason}")
        return None


def execute_pending_move(
    original_parent_client_order_id: str,
    new_parent_client_order_id: str
) -> int:
    """
    Execute a pending move by setting the new parent and marking as executed.
    
    Called when a pre-marked order cancels and the new parent has been created.
    Sets new_parent_client_order_id, moved_at timestamp, and move_on_cancel to FALSE.
    
    Args:
        original_parent_client_order_id: The original parent being moved.
        new_parent_client_order_id: The new parent that was created.
    
    Returns:
        Number of rows updated (0 or 1).
        
    Example:
        >>> result = execute_pending_move(
        ...     original_parent_client_order_id="old_parent_uuid",
        ...     new_parent_client_order_id="new_parent_uuid"
        ... )
        >>> if result > 0:
        ...     print("Pending move executed")
    """
    query = """
    UPDATE order_moves
    SET new_parent_client_order_id = %s,
        moved_at = CURRENT_TIMESTAMP,
        move_on_cancel = FALSE
    WHERE original_parent_client_order_id = %s
      AND move_on_cancel = TRUE
      AND new_parent_client_order_id IS NULL
    """
    params = (new_parent_client_order_id, original_parent_client_order_id)
    
    try:
        result = DB_CLIENT.execute_update(query, params)
        if result > 0:
            logger.info(
                f"Pending move executed: {original_parent_client_order_id} "
                f"-> {new_parent_client_order_id}"
            )
        return result
    except Exception as e:
        logger.error(f"Error executing pending move for {original_parent_client_order_id}: {type(e).__name__}: {e}")
        return 0
