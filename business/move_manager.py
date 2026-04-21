"""Move manager for handling cancelled order moves.

This module provides business logic for the "move" mechanism where a cancelled
parent order is replaced with a new parent order. Unlike the regular child order
mechanism, moved orders replace the parent/child relationship entirely.

Key Concepts:
- When a parent order is cancelled and marked for move, a new parent order is created
- The new parent order has similar configuration to the original (product, side, etc.)
- The original parent order remains in the database for audit purposes
- The move relationship is tracked in the order_moves table
- All child orders of the original parent are NOT automatically moved

Example:
    >>> manager = MoveManager()
    >>> 
    >>> # Move a cancelled parent order to a new one
    >>> result = manager.move_order(
    ...     original_parent_client_order_id="old_parent_uuid",
    ...     new_order_details={
    ...         "product_id": "BTC-USDC",
    ...         "side": "BUY",
    ...         "size": 1.0,
    ...         "price": 42500.0,
    ...         "target_movement": 0.005,
    ...         "target_movement_type": "P"
    ...     },
    ...     reason="cancelled_user_request"
    ... )
    >>> if result["success"]:
    ...     print(f"New parent order: {result['new_parent_client_order_id']}")
"""

import uuid
from typing import Dict, Any, Optional, Tuple

from database.order import (
    get_parent_order,
    insert_order_parent,
    insert_order_move,
    get_order_move,
    get_pending_move,
    has_pending_move,
    create_pending_move,
    execute_pending_move,
    get_order_moves_by_new_parent,
)
from configuration import OrderBook


class MoveManager:
    """Manages the move mechanism for cancelled parent orders.
    
    A "move" replaces a cancelled parent order with a new parent order,
    breaking the parent-child relationship and starting fresh with a new parent.
    
    Attributes:
        orderbook: Reference to the OrderBook for state management.
    """

    def __init__(self, orderbook: Optional[OrderBook] = None):
        """Initialize MoveManager.
        
        Args:
            orderbook: OrderBook instance for state tracking. If None, uses
                      the default OrderBook from configuration.
        """
        self.orderbook = orderbook or OrderBook()

    def can_move_order(self, original_parent_client_order_id: str) -> Tuple[bool, str]:
        """Check if an order can be moved.
        
        Prerequisites for moving an order:
        - Order must exist in order_parent table
        - Order must not already be moved
        - Order must be in a moveable status (typically CANCELLED or FILLED)
        
        Args:
            original_parent_client_order_id: The client_order_id of the parent to move.
        
        Returns:
            Tuple of (can_move: bool, reason: str).
            
        Example:
            >>> manager = MoveManager()
            >>> can_move, reason = manager.can_move_order("parent_uuid")
            >>> if not can_move:
            ...     print(f"Cannot move: {reason}")
        """
        # Check if order exists
        parent = get_parent_order(original_parent_client_order_id)
        if not parent:
            return False, f"Parent order not found: {original_parent_client_order_id}"

        # Check if order has already been moved (completed move, not pending)
        existing_move = get_order_move(original_parent_client_order_id)
        if existing_move and existing_move.get('new_parent_client_order_id'):
            # Only reject if the move is completed (has a new parent)
            return (
                False,
                f"Order already moved to {existing_move['new_parent_client_order_id']} "
                f"at {existing_move['moved_at']}"
            )

        # Order can be moved
        return True, "Order is eligible for move"

    def move_order(
        self,
        original_parent_client_order_id: str,
        new_order_details: Dict[str, Any],
        reason: str = "cancelled_move",
        notes: str = None
    ) -> Dict[str, Any]:
        """Move a cancelled parent order to a new parent order.
        
        Creates a new parent order with the specified details and records the move
        relationship. The original parent order remains in the database with updated
        status.
        
        Args:
            original_parent_client_order_id: The client_order_id of the order being moved (cancelled).
            new_order_details: Dict with new parent order configuration:
                - product_id (required): Trading pair (e.g., 'BTC-USDC')
                - side (required): 'BUY' or 'SELL'
                - size (required): Order quantity
                - price (required): Order price
                - target_movement (required): Target profit/movement percentage or amount
                - target_movement_type (optional): 'P' for percentage, 'A' for absolute (default 'P')
                - max_order_replacement (optional): Max follow-ups for new parent (default 0)
            reason: Reason for the move. Examples: 'cancelled_move', 'user_move', 'price_adjustment'.
            notes: Optional additional context about the move.
        
        Returns:
            Dict with result information:
            {
                "success": bool,
                "message": str,
                "original_parent_client_order_id": str,
                "new_parent_client_order_id": str or None,
                "move_id": int or None,
                "reason": str,
                "error": str or None
            }
            
        Example:
            >>> result = manager.move_order(
            ...     original_parent_client_order_id="old_parent_abc123",
            ...     new_order_details={
            ...         "product_id": "BTC-USDC",
            ...         "side": "BUY",
            ...         "size": 1.5,
            ...         "price": 42500.0,
            ...         "target_movement": 0.005,
            ...         "target_movement_type": "P",
            ...         "max_order_replacement": 11
            ...     },
            ...     reason="user_cancelled_and_moved",
            ...     notes="Cancelled due to price conditions change"
            ... )
            >>> if result["success"]:
            ...     print(f"New parent: {result['new_parent_client_order_id']}")
        """
        # Validate the order can be moved
        can_move, validation_reason = self.can_move_order(original_parent_client_order_id)
        if not can_move:
            return {
                "success": False,
                "message": validation_reason,
                "original_parent_client_order_id": original_parent_client_order_id,
                "new_parent_client_order_id": None,
                "move_id": None,
                "reason": reason,
                "error": validation_reason
            }

        # Validate new order details
        required_fields = ["product_id", "side", "size", "price", "target_movement"]
        missing_fields = [f for f in required_fields if f not in new_order_details]
        if missing_fields:
            error_msg = f"Missing required fields in new_order_details: {', '.join(missing_fields)}"
            return {
                "success": False,
                "message": error_msg,
                "original_parent_client_order_id": original_parent_client_order_id,
                "new_parent_client_order_id": None,
                "move_id": None,
                "reason": reason,
                "error": error_msg
            }

        try:
            # Generate new parent order ID
            new_parent_client_order_id = str(uuid.uuid4())

            # Extract order details
            product_id = new_order_details["product_id"]
            side = new_order_details["side"]
            size = float(new_order_details["size"])
            price = float(new_order_details["price"])
            target_movement = float(new_order_details["target_movement"])
            target_movement_type = new_order_details.get("target_movement_type", "P")
            max_order_replacement = int(new_order_details.get("max_order_replacement", 0))

            # Insert new parent order into database
            parent_id = insert_order_parent(
                client_order_id=new_parent_client_order_id,
                product_id=product_id,
                side=side,
                size=size,
                price=price,
                target_movement=target_movement,
                target_movement_type=target_movement_type,
                max_order_replacement=max_order_replacement,
                current_order_replacement=0,
                status="pending"
            )

            if parent_id is None:
                return {
                    "success": False,
                    "message": "Failed to insert new parent order into database",
                    "original_parent_client_order_id": original_parent_client_order_id,
                    "new_parent_client_order_id": new_parent_client_order_id,
                    "move_id": None,
                    "reason": reason,
                    "error": "Database insertion failed"
                }

            # Record the move relationship
            move_id = insert_order_move(
                original_parent_client_order_id=original_parent_client_order_id,
                new_parent_client_order_id=new_parent_client_order_id,
                reason=reason,
                notes=notes
            )

            if move_id is None:
                return {
                    "success": False,
                    "message": "Failed to record move relationship in database",
                    "original_parent_client_order_id": original_parent_client_order_id,
                    "new_parent_client_order_id": new_parent_client_order_id,
                    "move_id": None,
                    "reason": reason,
                    "error": "Failed to insert move record"
                }

            # Update orderbook in-memory state if available
            if self.orderbook:
                try:
                    # Add new parent to orderbook
                    self.orderbook.parent_order_ids[new_parent_client_order_id] = {
                        "client_order_id": new_parent_client_order_id,
                        "product_id": product_id,
                        "side": side,
                        "max_order_replacement": max_order_replacement,
                        "current_order_replacement": 0,
                        "target_movement": target_movement,
                        "target_movement_type": target_movement_type,
                        "orders": []
                    }
                except Exception as e:
                    print(f"Warning: Failed to update orderbook state: {e}")
                    # This is non-critical, continue with success

            return {
                "success": True,
                "message": f"Order moved successfully from {original_parent_client_order_id} "
                          f"to {new_parent_client_order_id}",
                "original_parent_client_order_id": original_parent_client_order_id,
                "new_parent_client_order_id": new_parent_client_order_id,
                "move_id": move_id,
                "reason": reason,
                "error": None
            }

        except Exception as e:
            error_msg = f"Unexpected error during move: {str(e)}"
            return {
                "success": False,
                "message": error_msg,
                "original_parent_client_order_id": original_parent_client_order_id,
                "new_parent_client_order_id": None,
                "move_id": None,
                "reason": reason,
                "error": error_msg
            }

    def get_move_history(self, client_order_id: str) -> Dict[str, Any]:
        """Get the move history for an order (if any).
        
        Args:
            client_order_id: The client_order_id to check.
        
        Returns:
            Dict with move information:
            {
                "has_moved": bool,
                "is_original": bool,
                "is_replacement": bool,
                "original_parent_client_order_id": str or None,
                "new_parent_client_order_id": str or None,
                "moved_at": timestamp or None,
                "reason": str or None
            }
        """
        move = get_order_move(client_order_id)
        
        if move:
            # This was an original parent that was moved
            return {
                "has_moved": True,
                "is_original": True,
                "is_replacement": False,
                "original_parent_client_order_id": client_order_id,
                "new_parent_client_order_id": move["new_parent_client_order_id"],
                "moved_at": move["moved_at"],
                "reason": move["reason"],
                "notes": move.get("notes")
            }

        # Check if this is a replacement parent (moved to this order from another)
        moves = get_order_moves_by_new_parent(client_order_id)
        if moves:
            latest_move = moves[0]
            return {
                "has_moved": True,
                "is_original": False,
                "is_replacement": True,
                "original_parent_client_order_id": latest_move["original_parent_client_order_id"],
                "new_parent_client_order_id": client_order_id,
                "moved_at": latest_move["moved_at"],
                "reason": latest_move["reason"],
                "notes": latest_move.get("notes")
            }

        # No move history
        return {
            "has_moved": False,
            "is_original": False,
            "is_replacement": False,
            "original_parent_client_order_id": None,
            "new_parent_client_order_id": None,
            "moved_at": None,
            "reason": None
        }

    def pre_mark_for_move(
        self,
        original_parent_client_order_id: str,
        new_order_details: Dict[str, Any],
        reason: str = "auto_move_scheduled",
        notes: str = None
    ) -> Dict[str, Any]:
        """Pre-mark an order for automatic move when it cancels (for automation).
        
        Creates a pending move record that will execute automatically when the
        order cancels. Useful for automation: "If this order cancels, move to strategy B".
        
        Args:
            original_parent_client_order_id: The client_order_id to pre-mark.
            new_order_details: Dict with new parent configuration:
                - product_id (required): Trading pair (e.g., 'BTC-USDC')
                - side (required): 'BUY' or 'SELL'
                - size (required): Order quantity
                - price (required): Order price
                - target_movement (required): Target profit/movement percentage or amount
                - target_movement_type (optional): 'P' for percentage, 'A' for absolute (default 'P')
                - max_order_replacement (optional): Max follow-ups (default 0)
            reason: Reason for pending move (default 'auto_move_scheduled').
            notes: Optional additional context.
        
        Returns:
            Dict with result:
            {
                "success": bool,
                "message": str,
                "move_id": int or None,
                "original_parent_client_order_id": str,
                "reason": str,
                "error": str or None
            }
            
        Example:
            >>> result = move_manager.pre_mark_for_move(
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
            ...     notes="Switch to sell if cancelled"
            ... )
            >>> if result["success"]:
            ...     print(f"Pre-marked for move: {result['move_id']}")
        """
        # Validate the order exists
        parent = get_parent_order(original_parent_client_order_id)
        if not parent:
            return {
                "success": False,
                "message": f"Parent order not found: {original_parent_client_order_id}",
                "move_id": None,
                "original_parent_client_order_id": original_parent_client_order_id,
                "reason": reason,
                "error": f"Parent order not found: {original_parent_client_order_id}"
            }

        # Check if already pending move
        if has_pending_move(original_parent_client_order_id):
            return {
                "success": False,
                "message": f"Order already has a pending move",
                "move_id": None,
                "original_parent_client_order_id": original_parent_client_order_id,
                "reason": reason,
                "error": "Order already has a pending move"
            }

        # Validate new order details
        required_fields = ["product_id", "side", "size", "price", "target_movement"]
        missing_fields = [f for f in required_fields if f not in new_order_details]
        if missing_fields:
            error_msg = f"Missing required fields in new_order_details: {', '.join(missing_fields)}"
            return {
                "success": False,
                "message": error_msg,
                "move_id": None,
                "original_parent_client_order_id": original_parent_client_order_id,
                "reason": reason,
                "error": error_msg
            }

        try:
            # Create pending move record
            move_id = create_pending_move(
                original_parent_client_order_id=original_parent_client_order_id,
                new_order_details=new_order_details,
                reason=reason,
                notes=notes
            )

            if move_id is None:
                return {
                    "success": False,
                    "message": "Failed to create pending move record",
                    "move_id": None,
                    "original_parent_client_order_id": original_parent_client_order_id,
                    "reason": reason,
                    "error": "Database insertion failed"
                }

            return {
                "success": True,
                "message": f"Order pre-marked for automatic move on cancel (ID: {move_id})",
                "move_id": move_id,
                "original_parent_client_order_id": original_parent_client_order_id,
                "reason": reason,
                "error": None
            }

        except Exception as e:
            error_msg = f"Exception during pre-mark: {str(e)}"
            return {
                "success": False,
                "message": error_msg,
                "move_id": None,
                "original_parent_client_order_id": original_parent_client_order_id,
                "reason": reason,
                "error": error_msg
            }

    def execute_pending_move_for_order(
        self,
        original_parent_client_order_id: str
    ) -> Dict[str, Any]:
        """Execute a pending move for a cancelled order (called by order processor).
        
        When an order with a pending move cancels, this creates the new parent
        and executes the move. Called automatically by order processing when:
        - Order cancels
        - Pending move exists (move_on_cancel=True)
        - No manual move has been done yet
        
        Args:
            original_parent_client_order_id: The parent order that cancelled.
        
        Returns:
            Dict with result:
            {
                "success": bool,
                "message": str,
                "new_parent_client_order_id": str or None,
                "move_id": int or None,
                "error": str or None
            }
            
        Example:
            >>> # Called from order engine when cancelled order is processed
            >>> result = move_manager.execute_pending_move_for_order(
            ...     original_parent_client_order_id="parent_uuid"
            ... )
            >>> if result["success"]:
            ...     print(f"Pending move executed: {result['new_parent_client_order_id']}")
        """
        try:
            # Get the pending move
            pending_move = get_pending_move(original_parent_client_order_id)
            if not pending_move:
                return {
                    "success": False,
                    "message": "No pending move found for this order",
                    "new_parent_client_order_id": None,
                    "move_id": None,
                    "error": "No pending move"
                }

            # Extract new order details from notes (stored as JSON)
            import json
            notes = pending_move.get("notes", "{}")
            
            # Try to extract from the notes
            new_order_details = None
            try:
                # Notes should have format: "some text\n\nPending move config: {...}"
                if "Pending move config:" in notes:
                    config_part = notes.split("Pending move config:")[-1].strip()
                    new_order_details = json.loads(config_part)
            except (json.JSONDecodeError, IndexError):
                pass

            if not new_order_details:
                return {
                    "success": False,
                    "message": "Could not extract move configuration from pending move record",
                    "new_parent_client_order_id": None,
                    "move_id": pending_move["id"],
                    "error": "Could not extract move configuration"
                }

            # Execute the move using normal move_order logic
            result = self.move_order(
                original_parent_client_order_id=original_parent_client_order_id,
                new_order_details=new_order_details,
                reason=f"automated_{pending_move['reason']}",
                notes=f"Auto-executed: {pending_move.get('notes', '')}"
            )

            if result["success"]:
                # Mark the pending move as executed
                execute_pending_move(
                    original_parent_client_order_id=original_parent_client_order_id,
                    new_parent_client_order_id=result["new_parent_client_order_id"]
                )

                return {
                    "success": True,
                    "message": f"Pending move executed automatically",
                    "new_parent_client_order_id": result["new_parent_client_order_id"],
                    "move_id": result["move_id"],
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to execute pending move: {result['error']}",
                    "new_parent_client_order_id": None,
                    "move_id": pending_move["id"],
                    "error": result["error"]
                }

        except Exception as e:
            error_msg = f"Exception executing pending move: {str(e)}"
            return {
                "success": False,
                "message": error_msg,
                "new_parent_client_order_id": None,
                "move_id": None,
                "error": error_msg
            }
            result = self.move_order(
                original_parent_client_order_id=original_parent_client_order_id,
                new_order_details=new_order_details,
                reason=f"automated_{pending_move['reason']}",
                notes=f"Auto-executed: {pending_move.get('notes', '')}"
            )

            if result["success"]:
                # Mark the pending move as executed
                execute_pending_move(
                    original_parent_client_order_id=original_parent_client_order_id,
                    new_parent_client_order_id=result["new_parent_client_order_id"]
                )

                return {
                    "success": True,
                    "message": f"Pending move executed automatically",
                    "new_parent_client_order_id": result["new_parent_client_order_id"],
                    "move_id": result["move_id"],
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to execute pending move: {result['error']}",
                    "new_parent_client_order_id": None,
                    "move_id": pending_move["id"],
                    "error": result["error"]
                }

        except Exception as e:
            error_msg = f"Exception executing pending move: {str(e)}"
            return {
                "success": False,
                "message": error_msg,
                "new_parent_client_order_id": None,
                "move_id": None,
                "error": error_msg
            }
