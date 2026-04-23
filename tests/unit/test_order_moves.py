"""Tests for the order move mechanism.

This module tests the MoveManager class and database functions for moving
cancelled parent orders to new parent orders.

Test Coverage:
- Creating moves
- Validating move prerequisites
- Query move history
- Integration with OrderEngine
"""

import pytest
import uuid
from typing import Dict, Any

from business.move_manager import MoveManager
from database.order import (
    insert_order_parent,
    get_parent_order,
    get_order_move,
    get_order_moves_by_original_parent,
    get_order_moves_by_new_parent,
    has_order_moved,
    insert_order_move,
)
from configuration import OrderBook
from core.enums import OrderStatus


class TestMoveManager:
    """Test suite for MoveManager class."""

    @pytest.fixture
    def move_manager(self):
        """Create a MoveManager instance for testing."""
        return MoveManager(orderbook=OrderBook())

    @pytest.fixture
    def original_parent_order(self):
        """Create an original parent order for moving."""
        client_order_id = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=client_order_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            target_movement_type="P",
            max_order_replacement=11,
            current_order_replacement=0,
            status=OrderStatus.CANCELLED.value
        )
        return client_order_id

    def test_can_move_order_exists(self, move_manager, original_parent_order):
        """Test that can_move_order returns True for valid parent."""
        can_move, reason = move_manager.can_move_order(original_parent_order)
        assert can_move is True
        assert "eligible" in reason.lower()

    def test_can_move_order_not_found(self, move_manager):
        """Test that can_move_order returns False for non-existent order."""
        fake_id = str(uuid.uuid4())
        can_move, reason = move_manager.can_move_order(fake_id)
        assert can_move is False
        assert "not found" in reason.lower()

    def test_move_order_success(self, move_manager, original_parent_order):
        """Test successful order move."""
        result = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01,
                "target_movement_type": "P",
                "max_order_replacement": 5
            },
            reason="test_move",
            notes="Testing move functionality"
        )

        assert result["success"] is True
        assert result["new_parent_client_order_id"] is not None
        assert result["move_id"] is not None
        assert result["error"] is None

    def test_move_order_missing_fields(self, move_manager, original_parent_order):
        """Test move fails with missing required fields."""
        result = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "BUY",
                # Missing required fields
            },
            reason="test_move"
        )

        assert result["success"] is False
        assert "missing required fields" in result["error"].lower()

    def test_move_order_already_moved(self, move_manager, original_parent_order):
        """Test that order cannot be moved twice."""
        # First move
        result1 = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "BUY",
                "size": 1.0,
                "price": 42000.0,
                "target_movement": 0.005,
                "max_order_replacement": 11
            }
        )
        assert result1["success"] is True

        # Second move attempt should fail
        result2 = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01,
                "max_order_replacement": 5
            }
        )
        assert result2["success"] is False
        assert "already moved" in result2["error"].lower()

    def test_move_order_with_defaults(self, move_manager, original_parent_order):
        """Test move with default values."""
        result = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "ETH-USDC",
                "side": "BUY",
                "size": 10.0,
                "price": 2500.0,
                "target_movement": 0.01
                # target_movement_type defaults to "P"
                # max_order_replacement defaults to 0
            }
        )

        assert result["success"] is True

    def test_get_move_history_original(self, move_manager, original_parent_order):
        """Test getting move history for original parent."""
        # Perform a move
        move_result = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.75,
                "price": 42500.0,
                "target_movement": 0.007,
                "max_order_replacement": 8
            },
            reason="test_history"
        )

        # Check move history
        history = move_manager.get_move_history(original_parent_order)
        assert history["has_moved"] is True
        assert history["is_original"] is True
        assert history["is_replacement"] is False
        assert history["original_parent_client_order_id"] == original_parent_order
        assert history["new_parent_client_order_id"] == move_result["new_parent_client_order_id"]
        assert history["reason"] == "test_history"

    def test_get_move_history_replacement(self, move_manager, original_parent_order):
        """Test getting move history for replacement parent."""
        # Perform a move
        move_result = move_manager.move_order(
            original_parent_client_order_id=original_parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.75,
                "price": 42500.0,
                "target_movement": 0.007,
                "max_order_replacement": 8
            },
            reason="test_replacement_history"
        )

        # Check move history for replacement
        new_parent_id = move_result["new_parent_client_order_id"]
        history = move_manager.get_move_history(new_parent_id)
        assert history["has_moved"] is True
        assert history["is_original"] is False
        assert history["is_replacement"] is True
        assert history["original_parent_client_order_id"] == original_parent_order
        assert history["new_parent_client_order_id"] == new_parent_id

    def test_get_move_history_no_move(self, move_manager):
        """Test getting move history for order with no move."""
        # Create a parent that was never moved
        unmoved_id = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=unmoved_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            status=OrderStatus.OPEN.value
        )

        history = move_manager.get_move_history(unmoved_id)
        assert history["has_moved"] is False
        assert history["is_original"] is False
        assert history["is_replacement"] is False


class TestMoveDatabase:
    """Test suite for move database functions."""

    @pytest.fixture
    def parent_orders(self):
        """Create parent orders for testing."""
        original_id = str(uuid.uuid4())
        new_id = str(uuid.uuid4())

        insert_order_parent(
            client_order_id=original_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            status=OrderStatus.CANCELLED.value
        )

        insert_order_parent(
            client_order_id=new_id,
            product_id="BTC-USDC",
            side="SELL",
            size=0.5,
            price=43000.0,
            target_movement=0.01,
            status=OrderStatus.PENDING.value
        )

        return original_id, new_id

    def test_insert_order_move(self, parent_orders):
        """Test inserting an order move record."""
        original_id, new_id = parent_orders

        move_id = insert_order_move(
            original_parent_client_order_id=original_id,
            new_parent_client_order_id=new_id,
            reason="test_insert",
            notes="Testing move insertion"
        )

        assert move_id is not None
        assert isinstance(move_id, int)

    def test_get_order_move(self, parent_orders):
        """Test retrieving a move record."""
        original_id, new_id = parent_orders

        insert_order_move(
            original_parent_client_order_id=original_id,
            new_parent_client_order_id=new_id,
            reason="test_get",
            notes="Testing move retrieval"
        )

        move = get_order_move(original_id)
        assert move is not None
        assert move["original_parent_client_order_id"] == original_id
        assert move["new_parent_client_order_id"] == new_id
        assert move["reason"] == "test_get"

    def test_get_order_moves_by_original_parent(self, parent_orders):
        """Test retrieving all moves by original parent."""
        original_id, new_id = parent_orders

        # Create two moves from the same original
        new_id2 = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=new_id2,
            product_id="BTC-USDC",
            side="BUY",
            size=2.0,
            price=41000.0,
            target_movement=0.003,
            status=OrderStatus.PENDING.value
        )

        insert_order_move(original_id, new_id, reason="first_move")
        insert_order_move(original_id, new_id2, reason="second_move")

        moves = get_order_moves_by_original_parent(original_id)
        assert len(moves) == 2
        assert moves[0]["reason"] == "second_move"  # Newest first

    def test_get_order_moves_by_new_parent(self, parent_orders):
        """Test retrieving moves by new parent."""
        original_id, new_id = parent_orders

        insert_order_move(original_id, new_id, reason="test_by_new")

        moves = get_order_moves_by_new_parent(new_id)
        assert len(moves) == 1
        assert moves[0]["original_parent_client_order_id"] == original_id

    def test_has_order_moved_original(self, parent_orders):
        """Test checking if original parent has moved."""
        original_id, new_id = parent_orders

        insert_order_move(original_id, new_id)

        assert has_order_moved(original_id) is True

    def test_has_order_moved_replacement(self, parent_orders):
        """Test checking if replacement parent exists."""
        original_id, new_id = parent_orders

        insert_order_move(original_id, new_id)

        assert has_order_moved(new_id) is True

    def test_has_order_moved_not_moved(self):
        """Test checking unmoved order."""
        unmoved_id = str(uuid.uuid4())

        insert_order_parent(
            client_order_id=unmoved_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            status=OrderStatus.OPEN.value
        )

        assert has_order_moved(unmoved_id) is False


class TestMoveIntegration:
    """Integration tests for move mechanism with other systems."""

    def test_move_preserves_original_parent(self, ):
        """Test that moving an order preserves the original parent record."""
        original_id = str(uuid.uuid4())
        original_price = 42000.0
        original_size = 1.0

        insert_order_parent(
            client_order_id=original_id,
            product_id="BTC-USDC",
            side="BUY",
            size=original_size,
            price=original_price,
            target_movement=0.005,
            status=OrderStatus.CANCELLED.value
        )

        # Move the order
        move_manager = MoveManager()
        result = move_manager.move_order(
            original_parent_client_order_id=original_id,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01,
                "max_order_replacement": 5
            }
        )

        # Verify original is unchanged
        original_parent = get_parent_order(original_id)
        assert original_parent is not None
        assert float(original_parent["price"]) == original_price
        assert float(original_parent["size"]) == original_size
        assert original_parent["status"] == "CANCELLED"

        # Verify new parent is created
        new_parent = get_parent_order(result["new_parent_client_order_id"])
        assert new_parent is not None
        assert float(new_parent["price"]) == 43000.0
        assert float(new_parent["size"]) == 0.5
        assert new_parent["side"] == "SELL"

    def test_move_with_orderbook(self):
        """Test move updates orderbook state correctly."""
        orderbook = OrderBook()
        move_manager = MoveManager(orderbook=orderbook)

        original_id = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=original_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            status=OrderStatus.CANCELLED.value
        )

        result = move_manager.move_order(
            original_parent_client_order_id=original_id,
            new_order_details={
                "product_id": "ETH-USDC",
                "side": "BUY",
                "size": 10.0,
                "price": 2500.0,
                "target_movement": 0.01,
                "max_order_replacement": 11
            }
        )

        # Verify orderbook has the new parent
        new_parent_id = result["new_parent_client_order_id"]
        assert new_parent_id in orderbook.parent_order_ids
        assert orderbook.parent_order_ids[new_parent_id]["product_id"] == "ETH-USDC"
        assert orderbook.parent_order_ids[new_parent_id]["side"] == "BUY"


class TestPendingMoves:
    """Test suite for pre-marked (pending) move automation."""

    @pytest.fixture
    def move_manager(self):
        """Create a MoveManager instance for testing."""
        return MoveManager(orderbook=OrderBook())

    @pytest.fixture
    def parent_order(self):
        """Create a parent order for pre-marking."""
        client_order_id = str(uuid.uuid4())
        insert_order_parent(
            client_order_id=client_order_id,
            product_id="BTC-USDC",
            side="BUY",
            size=1.0,
            price=42000.0,
            target_movement=0.005,
            status=OrderStatus.OPEN.value
        )
        return client_order_id

    def test_pre_mark_for_move(self, move_manager, parent_order):
        """Test pre-marking an order for automatic move."""
        result = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01,
                "max_order_replacement": 5
            },
            reason="scheduled_reversal",
            notes="Switch to sell if cancelled"
        )

        assert result["success"] is True
        assert result["move_id"] is not None
        assert result["error"] is None

    def test_pre_mark_missing_fields(self, move_manager, parent_order):
        """Test pre-mark fails with missing required fields."""
        result = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                # Missing required fields
            }
        )

        assert result["success"] is False
        assert "missing required fields" in result["error"].lower()

    def test_pre_mark_order_not_found(self, move_manager):
        """Test pre-mark fails for non-existent order."""
        fake_id = str(uuid.uuid4())
        result = move_manager.pre_mark_for_move(
            original_parent_client_order_id=fake_id,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "BUY",
                "size": 1.0,
                "price": 42000.0,
                "target_movement": 0.005
            }
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_pre_mark_duplicate_pending_move(self, move_manager, parent_order):
        """Test that order cannot be pre-marked twice."""
        # First pre-mark
        result1 = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01
            }
        )
        assert result1["success"] is True

        # Second pre-mark should fail
        result2 = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details={
                "product_id": "ETH-USDC",
                "side": "BUY",
                "size": 10.0,
                "price": 2500.0,
                "target_movement": 0.01
            }
        )
        assert result2["success"] is False
        assert "already has a pending move" in result2["error"].lower()

    def test_execute_pending_move_for_order(self, move_manager, parent_order):
        """Test executing a pending move when order cancels."""
        # Pre-mark the order
        pre_result = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details={
                "product_id": "BTC-USDC",
                "side": "SELL",
                "size": 0.5,
                "price": 43000.0,
                "target_movement": 0.01,
                "max_order_replacement": 3
            },
            reason="auto_reversal",
            notes="Automatic reversal when cancelled"
        )
        assert pre_result["success"] is True

        # Execute the pending move (simulating order cancellation)
        exec_result = move_manager.execute_pending_move_for_order(parent_order)

        assert exec_result["success"] is True
        assert exec_result["new_parent_client_order_id"] is not None
        assert exec_result["move_id"] is not None

        # Verify new parent was created with correct config
        new_parent = get_parent_order(exec_result["new_parent_client_order_id"])
        assert new_parent is not None
        assert new_parent["side"] == "SELL"
        assert float(new_parent["size"]) == 0.5

    def test_execute_pending_move_no_pending(self, move_manager, parent_order):
        """Test executing when no pending move exists."""
        result = move_manager.execute_pending_move_for_order(parent_order)

        assert result["success"] is False
        assert "no pending move" in result["error"].lower()

    def test_pending_move_stores_config(self, parent_order):
        """Test that pending move stores configuration for later execution."""
        from database.order import get_pending_move

        move_manager = MoveManager()
        
        config = {
            "product_id": "ETH-USDC",
            "side": "BUY",
            "size": 5.0,
            "price": 2500.0,
            "target_movement": 0.015,
            "max_order_replacement": 7
        }

        result = move_manager.pre_mark_for_move(
            original_parent_client_order_id=parent_order,
            new_order_details=config,
            reason="test_config",
            notes="Test config storage"
        )

        assert result["success"] is True

        # Retrieve the pending move
        pending = get_pending_move(parent_order)
        assert pending is not None
        assert pending["move_on_cancel"] is True
        assert pending["new_parent_client_order_id"] is None
        assert "Pending move config:" in pending["notes"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
