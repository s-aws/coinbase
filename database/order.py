"""
Order insertion and status management functions for parent and child order tables.

This module handles all database operations for parent and child orders,
including creation, insertion, batch operations, duplicate detection,
replacement tracking, and status updates.
It manages the parent-child order relationship for the trading engine.
"""

from database.database import PostgresDB
from typing import Dict, List, Any, Optional

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


def add_missing_order_parent_replacement_columns() -> None:
    """
    Add replacement tracking columns to an existing order_parent table.
    Safe to run repeatedly.
    """
    alter_queries = [
        """
        ALTER TABLE order_parent
        ADD COLUMN IF NOT EXISTS max_order_replacement INTEGER NOT NULL DEFAULT 0
        """,
        """
        ALTER TABLE order_parent
        ADD COLUMN IF NOT EXISTS current_order_replacement INTEGER NOT NULL DEFAULT 0
        """,
    ]

    with DB_CLIENT.get_cursor() as cursor:
        for query in alter_queries:
            cursor.execute(query)
        print("order_parent replacement columns done.")


def create_order_child_table() -> None:
    """
    Create the order_child table if it doesn't exist.
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
    max_order_replacement: int = 0,
    current_order_replacement: int = 0,
    status: str = "pending"
) -> Optional[int]:
    """
    Insert a parent order into the order_parent table.
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
            print(f"Parent order inserted: {client_order_id} (ID: {inserted_id})")
            return inserted_id

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
            print(
                f"Child order inserted: {client_order_id} "
                f"(ID: {inserted_id}, parent: {parent_client_order_id})"
            )
            return inserted_id

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
    """
    inserted_ids: List[Optional[int]] = []

    for order in orders:
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
            print(f"Skipping invalid order: {order}")
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

    return inserted_ids


def insert_order_child_batch(
    orders: List[Dict[str, Any]]
) -> int:
    """
    Insert multiple child orders at once.
    """
    total_inserted: int = 0

    for order in orders:
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
            print(f"Skipping invalid order: {order}")
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

    return total_inserted


def get_parent_order(client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a parent order by client_order_id.
    """
    query = "SELECT * FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return results[0] if results else None


def get_parent_orders() -> List[Dict[str, Any]]:
    """
    Retrieve all parent orders from the database.
    """
    query = "SELECT * FROM order_parent"
    return DB_CLIENT.execute_query(query)


def get_child_orders(parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all child orders for a parent order.
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
    """
    Check whether a child order already exists for the given parent and order template.
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
    """
    Retrieve the current replacement count for a parent order.
    """
    query = "SELECT current_order_replacement FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return int(results[0]["current_order_replacement"]) if results else None


def update_order_parent_status(
    client_order_id: str,
    status: str
) -> int:
    """
    Update the status of a parent order.
    """
    query = "UPDATE order_parent SET status = %s WHERE client_order_id = %s"
    params = (status, client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(f"Parent order status updated: {client_order_id} -> {status}")
    else:
        print(f"No parent order found with client_order_id: {client_order_id}")
    return result


def update_order_parent_replacement_count(
    client_order_id: str,
    current_order_replacement: int
) -> int:
    """
    Update the current replacement count for a parent order.
    """
    query = """
    UPDATE order_parent
    SET current_order_replacement = %s
    WHERE client_order_id = %s
    """
    params = (int(current_order_replacement), client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(
            f"Parent order replacement count updated: "
            f"{client_order_id} -> {current_order_replacement}"
        )
    else:
        print(f"No parent order found with client_order_id: {client_order_id}")
    return result


def increment_order_parent_replacement_count(client_order_id: str) -> Optional[int]:
    """
    Increment the current replacement count for a parent order.
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
        print(f"Parent order replacement count incremented: {client_order_id} -> {new_count}")
        return new_count

    print(f"No parent order found with client_order_id: {client_order_id}")
    return None


def update_order_parent_replacement_config(
    client_order_id: str,
    max_order_replacement: int,
    current_order_replacement: Optional[int] = None,
) -> int:
    """
    Update replacement configuration for a parent order.
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
        print(f"No parent order found with client_order_id: {client_order_id}")
    return result


def update_order_parent_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """
    Update status for multiple parent orders at once.
    """
    total_updated: int = 0

    for update in status_updates:
        client_order_id = update.get("client_order_id")
        status = update.get("status")

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
    """
    total_updated: int = 0

    for update in status_updates:
        client_order_id = update.get("client_order_id")
        status = update.get("status")

        if not all([client_order_id, status]):
            print(f"Skipping invalid status update: {update}")
            continue

        result = update_order_child_status(client_order_id, status)
        total_updated += result

    return total_updated
