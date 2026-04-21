"""Dashboard-specific helper functions for order management.

Provides simplified CRUD operations optimized for WebSocket dashboard requests.
"""

from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Any, Optional
from database.order import (
    get_parent_orders,
    get_parent_order,
    insert_order_parent,
    update_order_parent_status,
)


def _serialize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects for WebSocket transport.
    
    Converts:
    - Decimal to float
    - datetime to ISO format string
    - dict values recursively
    - list items recursively
    
    Args:
        obj: Object to convert (dict, list, or scalar).
        
    Returns:
        Object with all non-serializable types converted.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    else:
        return obj


def get_all_parent_orders() -> List[Dict[str, Any]]:
    """Get all parent orders formatted for dashboard display.
    
    Returns:
        List of parent order dicts with all fields (Decimals converted to float).
    """
    try:
        orders = get_parent_orders()
        return [_serialize_for_json(o) for o in orders]
    except Exception as e:
        print(f"Error fetching parent orders: {e}")
        return []


def get_parent_order_by_client_id(client_order_id: str) -> Optional[Dict[str, Any]]:
    """Get a single parent order by client_order_id.
    
    Args:
        client_order_id: The client order ID to look up.
        
    Returns:
        Order dict if found (Decimals converted to float), None otherwise.
    """
    try:
        order = get_parent_order(client_order_id)
        return _serialize_for_json(order) if order else None
    except Exception as e:
        print(f"Error fetching parent order {client_order_id}: {e}")
        return None


def insert_parent_order(
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    target_movement: Optional[float] = None,
    max_order_replacement: int = 0,
    status: str = "OPEN"
) -> Optional[int]:
    """Insert a new parent order.
    
    Args:
        client_order_id: Unique order ID.
        product_id: Product to trade.
        side: BUY or SELL.
        size: Order size.
        price: Order price.
        target_movement: Target profit/movement.
        max_order_replacement: Max follow-ups.
        status: Order status.
        
    Returns:
        Inserted order ID, or None on failure.
    """
    try:
        return insert_order_parent(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=float(size),
            price=float(price),
            target_movement=float(target_movement) if target_movement else 0.0,
            max_order_replacement=int(max_order_replacement),
            status=status
        )
    except Exception as e:
        print(f"Error inserting parent order: {e}")
        return None


def update_parent_order(
    client_order_id: str,
    update_data: Dict[str, Any]
) -> bool:
    """Update a parent order with new data.
    
    Args:
        client_order_id: The order to update.
        update_data: Dict with fields: size, price, target_movement, max_order_replacement, status.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        from database.database import PostgresDB
        db_client = PostgresDB()
        
        # Build dynamic UPDATE query
        updates = []
        params = []
        
        if 'size' in update_data:
            updates.append("size = %s")
            params.append(float(update_data['size']))
        
        if 'price' in update_data:
            updates.append("price = %s")
            params.append(float(update_data['price']))
        
        if 'target_movement' in update_data:
            updates.append("target_movement = %s")
            params.append(float(update_data['target_movement']) if update_data['target_movement'] else None)
        
        if 'max_order_replacement' in update_data:
            updates.append("max_order_replacement = %s")
            params.append(int(update_data['max_order_replacement']))
        
        if 'status' in update_data:
            updates.append("status = %s")
            params.append(update_data['status'])
        
        if not updates:
            return False
        
        # Add client_order_id parameter
        params.append(client_order_id)
        
        query = f"UPDATE order_parent SET {', '.join(updates)} WHERE client_order_id = %s"
        
        result = db_client.execute_update(query, params)
        return result > 0
        
    except Exception as e:
        print(f"Error updating parent order: {e}")
        return False


def delete_parent_order(client_order_id: str) -> bool:
    """Delete a parent order.
    
    Args:
        client_order_id: The order to delete.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        from database.database import PostgresDB
        db_client = PostgresDB()
        
        query = "DELETE FROM order_parent WHERE client_order_id = %s"
        result = db_client.execute_update(query, (client_order_id,))
        return result > 0
        
    except Exception as e:
        print(f"Error deleting parent order: {e}")
        return False
