"""Dashboard-specific helper functions for order management.

Provides simplified CRUD operations optimized for WebSocket dashboard requests.
"""

from decimal import Decimal
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional
from database.order import (
    get_parent_order,
)
from calculation.price_validation import normalize_price_for_product
from core.enums import PriceRoundingPolicy


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


def update_parent_order(
    client_order_id: str,
    update_data: Dict[str, Any],
    *,
    metadata_reader: Callable[[str], Mapping[str, Any]],
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
            existing_order = get_parent_order(client_order_id)
            if not existing_order:
                raise ValueError(
                    f"Parent order not found: {client_order_id}"
                )
            price_check = normalize_price_for_product(
                update_data['price'],
                product_id=existing_order.get('product_id'),
                side=existing_order.get('side'),
                policy=PriceRoundingPolicy.SIDE_CONSERVATIVE,
                metadata_reader=metadata_reader,
            )
            if not price_check.ok or price_check.effective_price is None:
                raise ValueError(
                    "Parent order update rejected at price boundary: "
                    f"{price_check.reason}"
                )
            updates.append("price = %s")
            params.append(float(price_check.effective_price))
        
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
