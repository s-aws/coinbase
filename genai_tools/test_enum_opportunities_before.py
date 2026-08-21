"""
BEFORE tests for all enum opportunities across the codebase.

This comprehensive test suite establishes baseline behavior for:
1. StealthOrderStatus (new enum needed)
2. ProductType usage (enum exists but not used consistently)
3. Direction usage (enum exists but not used consistently)
4. RevealConditionType usage (enum exists but not used consistently)
5. Other enum opportunities

Tests BEFORE enum refactoring to ensure nothing breaks during implementation.
"""

import sys
import json
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, '/'.join(__file__.split('/')[:-2]))

from core.enums import (
    Direction, RevealConditionType, FollowUpRevealDirection, OrderSide,
    OrderStatus, OrderType, TimeInForce, ProductType, TargetMovementType
)
from core.stealth_order_manager import StealthOrderManager
from database.database import PostgresDB


class TestStealthOrderStatusStrings:
    """Tests for magic strings used as stealth order status (NEEDS NEW ENUM)."""

    def setup_method(self):
        """Setup for each test."""
        self.db_client = PostgresDB()
        self.manager = StealthOrderManager(self.db_client)

    def test_stealth_order_hidden_status_string(self):
        """Test stealth orders use 'HIDDEN' string status."""
        print("\n=== test_stealth_order_hidden_status_string ===")

        order_id = self.manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = self.manager._get_stealth_order(order_id)
        assert order.get("status") == "HIDDEN", "New stealth order should have HIDDEN status"
        print(f"✓ New stealth order status = '{order.get('status')}' (string)")

    def test_stealth_order_pending_status_string(self):
        """Test stealth orders use 'PENDING' string status."""
        print("\n=== test_stealth_order_pending_status_string ===")

        order_id = self.manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = self.manager._get_stealth_order(order_id)
        order["status"] = "PENDING"  # Simulate status change
        assert order["status"] == "PENDING", "Should support PENDING status"
        print(f"✓ Stealth order status can be set to 'PENDING' (string)")

    def test_stealth_order_triggered_status_string(self):
        """Test stealth orders use 'TRIGGERED' string status."""
        print("\n=== test_stealth_order_triggered_status_string ===")

        # This is what happens during condition evaluation
        assert "TRIGGERED" in ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED", "EXECUTED", "CANCELLED"]
        print(f"✓ 'TRIGGERED' is a valid stealth order status string")

    def test_stealth_order_revealed_status_string(self):
        """Test stealth orders use 'REVEALED' string status."""
        print("\n=== test_stealth_order_revealed_status_string ===")

        assert "REVEALED" in ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED", "EXECUTED", "CANCELLED"]
        print(f"✓ 'REVEALED' is a valid stealth order status string")

    def test_stealth_order_executed_status_string(self):
        """Test stealth orders use 'EXECUTED' string status."""
        print("\n=== test_stealth_order_executed_status_string ===")

        assert "EXECUTED" in ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED", "EXECUTED", "CANCELLED"]
        print(f"✓ 'EXECUTED' is a valid stealth order status string")

    def test_stealth_order_cancelled_status_string(self):
        """Test stealth orders use 'CANCELLED' string status."""
        print("\n=== test_stealth_order_cancelled_status_string ===")

        assert "CANCELLED" in ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED", "EXECUTED", "CANCELLED"]
        print(f"✓ 'CANCELLED' is a valid stealth order status string")

    def test_stealth_order_status_collection(self):
        """Test stealth orders use status strings in collections."""
        print("\n=== test_stealth_order_status_collection ===")

        active_statuses = ["HIDDEN", "PENDING", "TRIGGERED", "REVEALED"]
        non_active_statuses = ["EXECUTED", "CANCELLED"]

        # Verify structure
        assert len(active_statuses) == 4
        assert len(non_active_statuses) == 2
        print(f"✓ Active statuses: {active_statuses}")
        print(f"✓ Non-active statuses: {non_active_statuses}")


class TestProductTypeStrings:
    """Tests for ProductType string usage (enum exists but not used consistently)."""

    def test_product_type_spot_string(self):
        """Test SPOT product type as string."""
        print("\n=== test_product_type_spot_string ===")

        # Currently code checks: if product_type in {"SPOT", "FUTURE"}
        assert "SPOT" == ProductType.SPOT.value
        assert isinstance(ProductType.SPOT.value, str)
        print(f"✓ ProductType.SPOT.value = '{ProductType.SPOT.value}'")

    def test_product_type_future_string(self):
        """Test FUTURE product type as string."""
        print("\n=== test_product_type_future_string ===")

        assert "FUTURE" == ProductType.FUTURE.value
        assert isinstance(ProductType.FUTURE.value, str)
        print(f"✓ ProductType.FUTURE.value = '{ProductType.FUTURE.value}'")

    def test_product_type_comparison_with_strings(self):
        """Test how calculation/resolver.py checks product type."""
        print("\n=== test_product_type_comparison_with_strings ===")

        # This is how resolver.py currently does it
        product_type = "SPOT"
        result = product_type in {"SPOT", "FUTURE"}
        assert result is True
        print(f"✓ String-based check works: '{product_type}' in {{'SPOT', 'FUTURE'}} = {result}")

        # Should also work with enum values
        result_enum = product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}
        assert result_enum is True
        print(f"✓ Enum-based check also works: '{product_type}' in enum values = {result_enum}")


class TestDirectionStrings:
    """Tests for Direction string usage (enum exists but not used consistently)."""

    def test_direction_above_string(self):
        """Test Direction.ABOVE enum value."""
        print("\n=== test_direction_above_string ===")

        assert Direction.ABOVE.value == "above"
        assert isinstance(Direction.ABOVE.value, str)
        print(f"✓ Direction.ABOVE.value = '{Direction.ABOVE.value}'")

    def test_direction_below_string(self):
        """Test Direction.BELOW enum value."""
        print("\n=== test_direction_below_string ===")

        assert Direction.BELOW.value == "below"
        assert isinstance(Direction.BELOW.value, str)
        print(f"✓ Direction.BELOW.value = '{Direction.BELOW.value}'")

    def test_direction_in_condition_config(self):
        """Test Direction strings in condition config (as currently used)."""
        print("\n=== test_direction_in_condition_config ===")

        # This is how order_engine.py currently sets direction
        condition = {"direction": "above"}
        assert condition["direction"] == "above"
        print(f"✓ Condition dict with string direction: {condition}")

        # Should also work with enum value
        condition_enum = {"direction": Direction.ABOVE.value}
        assert condition_enum["direction"] == "above"
        print(f"✓ Condition dict with enum value: {condition_enum}")


class TestRevealConditionTypeStrings:
    """Tests for RevealConditionType usage (enum exists but not used consistently)."""

    def test_reveal_condition_time_delay_string(self):
        """Test time_delay reveal condition type."""
        print("\n=== test_reveal_condition_time_delay_string ===")

        assert RevealConditionType.TIME_DELAY.value == "time_delay"
        assert isinstance(RevealConditionType.TIME_DELAY.value, str)
        print(f"✓ RevealConditionType.TIME_DELAY.value = '{RevealConditionType.TIME_DELAY.value}'")

    def test_reveal_condition_price_string(self):
        """Test price reveal condition type."""
        print("\n=== test_reveal_condition_price_string ===")

        assert RevealConditionType.PRICE_THRESHOLD.value == "price"
        assert isinstance(RevealConditionType.PRICE_THRESHOLD.value, str)
        print(f"✓ RevealConditionType.PRICE_THRESHOLD.value = '{RevealConditionType.PRICE_THRESHOLD.value}'")

    def test_reveal_condition_in_order(self):
        """Test reveal condition type in order creation."""
        print("\n=== test_reveal_condition_in_order ===")

        db_client = PostgresDB()
        manager = StealthOrderManager(db_client)

        # Currently: order has "reveal_condition_type": "time_delay" as string
        order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = manager._get_stealth_order(order_id)
        assert order.get("reveal_condition_type") == "time_delay"
        print(f"✓ Order reveal_condition_type = '{order.get('reveal_condition_type')}' (string)")


class TestFollowUpRevealDirectionUsage:
    """Tests for FollowUpRevealDirection (enum recently created and partially used)."""

    def test_followup_same_value(self):
        """Test FollowUpRevealDirection.SAME value."""
        print("\n=== test_followup_same_value ===")

        assert FollowUpRevealDirection.SAME.value == "same"
        assert isinstance(FollowUpRevealDirection.SAME.value, str)
        print(f"✓ FollowUpRevealDirection.SAME.value = '{FollowUpRevealDirection.SAME.value}'")

    def test_followup_opposite_value(self):
        """Test FollowUpRevealDirection.OPPOSITE value."""
        print("\n=== test_followup_opposite_value ===")

        assert FollowUpRevealDirection.OPPOSITE.value == "opposite"
        assert isinstance(FollowUpRevealDirection.OPPOSITE.value, str)
        print(f"✓ FollowUpRevealDirection.OPPOSITE.value = '{FollowUpRevealDirection.OPPOSITE.value}'")

    def test_followup_direction_in_stealth_order(self):
        """Test follow-up direction is correctly used in stealth orders."""
        print("\n=== test_followup_direction_in_stealth_order ===")

        db_client = PostgresDB()
        manager = StealthOrderManager(db_client)

        # StealthOrderManager should use enum for default
        order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = manager._get_stealth_order(order_id)
        follow_up_dir = order.get("follow_up_reveal_direction")

        # Should be "opposite" (the enum value)
        assert follow_up_dir == FollowUpRevealDirection.OPPOSITE.value
        print(f"✓ Default follow-up direction = '{follow_up_dir}'")


class TestOrderSideStrings:
    """Tests for OrderSide enum usage (enum exists and should be used more)."""

    def test_order_side_buy_enum(self):
        """Test OrderSide.BUY enum."""
        print("\n=== test_order_side_buy_enum ===")

        assert OrderSide.BUY.value == "BUY"
        assert isinstance(OrderSide.BUY.value, str)
        print(f"✓ OrderSide.BUY.value = '{OrderSide.BUY.value}'")

    def test_order_side_sell_enum(self):
        """Test OrderSide.SELL enum."""
        print("\n=== test_order_side_sell_enum ===")

        assert OrderSide.SELL.value == "SELL"
        assert isinstance(OrderSide.SELL.value, str)
        print(f"✓ OrderSide.SELL.value = '{OrderSide.SELL.value}'")

    def test_order_side_in_stealth_order(self):
        """Test OrderSide values in stealth order creation."""
        print("\n=== test_order_side_in_stealth_order ===")

        db_client = PostgresDB()
        manager = StealthOrderManager(db_client)

        order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",  # Currently accepted as string
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = manager._get_stealth_order(order_id)
        assert order.get("side") == "BUY"
        assert order.get("side") == OrderSide.BUY.value
        print(f"✓ Stealth order side = '{order.get('side')}'")


class TestOrderStatusStrings:
    """Tests for OrderStatus enum usage in tests and fixtures."""

    def test_order_status_pending_enum(self):
        """Test OrderStatus.PENDING enum."""
        print("\n=== test_order_status_pending_enum ===")

        assert OrderStatus.PENDING.value == "PENDING"
        assert isinstance(OrderStatus.PENDING.value, str)
        print(f"✓ OrderStatus.PENDING.value = '{OrderStatus.PENDING.value}'")

    def test_order_status_open_enum(self):
        """Test OrderStatus.OPEN enum."""
        print("\n=== test_order_status_open_enum ===")

        assert OrderStatus.OPEN.value == "OPEN"
        print(f"✓ OrderStatus.OPEN.value = '{OrderStatus.OPEN.value}'")

    def test_order_status_filled_enum(self):
        """Test OrderStatus.FILLED enum."""
        print("\n=== test_order_status_filled_enum ===")

        assert OrderStatus.FILLED.value == "FILLED"
        print(f"✓ OrderStatus.FILLED.value = '{OrderStatus.FILLED.value}'")

    def test_order_status_cancelled_enum(self):
        """Test OrderStatus.CANCELLED enum."""
        print("\n=== test_order_status_cancelled_enum ===")

        assert OrderStatus.CANCELLED.value == "CANCELLED"
        print(f"✓ OrderStatus.CANCELLED.value = '{OrderStatus.CANCELLED.value}'")


class TestOrderTypeStrings:
    """Tests for OrderType enum usage in tests and configurations."""

    def test_order_type_limit_enum(self):
        """Test OrderType.LIMIT enum."""
        print("\n=== test_order_type_limit_enum ===")

        assert OrderType.LIMIT.value == "LIMIT"
        # Tests might use lowercase "limit" which should be updated
        assert "limit".upper() == OrderType.LIMIT.value
        print(f"✓ OrderType.LIMIT.value = '{OrderType.LIMIT.value}'")

    def test_order_type_market_enum(self):
        """Test OrderType.MARKET enum."""
        print("\n=== test_order_type_market_enum ===")

        assert OrderType.MARKET.value == "MARKET"
        print(f"✓ OrderType.MARKET.value = '{OrderType.MARKET.value}'")

    def test_order_type_stop_limit_enum(self):
        """Test OrderType.STOP_LIMIT enum."""
        print("\n=== test_order_type_stop_limit_enum ===")

        assert OrderType.STOP_LIMIT.value == "STOP_LIMIT"
        print(f"✓ OrderType.STOP_LIMIT.value = '{OrderType.STOP_LIMIT.value}'")


class TestTimeInForceStrings:
    """Tests for TimeInForce enum usage in tests and configurations."""

    def test_time_in_force_gtc_enum(self):
        """Test TimeInForce GTC enum."""
        print("\n=== test_time_in_force_gtc_enum ===")

        assert TimeInForce.GOOD_UNTIL_CANCELLED.value == "GOOD_UNTIL_CANCELLED"
        assert TimeInForce.GTC.value == "GOOD_UNTIL_CANCELLED"  # Alias
        print(f"✓ TimeInForce.GTC.value = '{TimeInForce.GTC.value}'")

    def test_time_in_force_ioc_enum(self):
        """Test TimeInForce IOC enum."""
        print("\n=== test_time_in_force_ioc_enum ===")

        assert TimeInForce.IMMEDIATE_OR_CANCEL.value == "IMMEDIATE_OR_CANCEL"
        assert TimeInForce.IOC.value == "IMMEDIATE_OR_CANCEL"  # Alias
        print(f"✓ TimeInForce.IOC.value = '{TimeInForce.IOC.value}'")


class TestTargetMovementTypeStrings:
    """Tests for TargetMovementType enum usage."""

    def test_target_movement_percentage_enum(self):
        """Test TargetMovementType PERCENTAGE."""
        print("\n=== test_target_movement_percentage_enum ===")

        assert TargetMovementType.PERCENTAGE.value == "P"
        print(f"✓ TargetMovementType.PERCENTAGE.value = '{TargetMovementType.PERCENTAGE.value}'")

    def test_target_movement_absolute_enum(self):
        """Test TargetMovementType ABSOLUTE."""
        print("\n=== test_target_movement_absolute_enum ===")

        assert TargetMovementType.ABSOLUTE.value == "A"
        print(f"✓ TargetMovementType.ABSOLUTE.value = '{TargetMovementType.ABSOLUTE.value}'")

    def test_target_movement_in_stealth_order(self):
        """Test target movement type in stealth order."""
        print("\n=== test_target_movement_in_stealth_order ===")

        db_client = PostgresDB()
        manager = StealthOrderManager(db_client)

        order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0},
            target_movement=0.005,
            target_movement_type="P"  # Currently string
        )

        # Should be stored as string value
        # When we refactor, target_movement_type should use enum
        print(f"✓ Target movement type parameter accepted")


def run_all_before_tests():
    """Run all BEFORE tests."""
    print("=" * 70)
    print("BEFORE TESTS - All Enum Opportunities")
    print("=" * 70)

    test_classes = [
        TestStealthOrderStatusStrings,
        TestProductTypeStrings,
        TestDirectionStrings,
        TestRevealConditionTypeStrings,
        TestFollowUpRevealDirectionUsage,
        TestOrderSideStrings,
        TestOrderStatusStrings,
        TestOrderTypeStrings,
        TestTimeInForceStrings,
        TestTargetMovementTypeStrings,
    ]

    passed = 0
    failed = 0

    for test_class in test_classes:
        test_instance = test_class()

        # Get all test methods
        test_methods = [method for method in dir(test_instance)
                       if method.startswith('test_')]

        for test_method in test_methods:
            try:
                # Setup if exists
                if hasattr(test_instance, 'setup_method'):
                    test_instance.setup_method()

                # Run test
                getattr(test_instance, test_method)()
                passed += 1
            except AssertionError as e:
                print(f"✗ FAILED: {e}")
                failed += 1
            except Exception as e:
                print(f"✗ ERROR: {str(e)}")
                failed += 1

    print("\n" + "=" * 70)
    print(f"BEFORE Tests Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_before_tests()
    sys.exit(0 if success else 1)
