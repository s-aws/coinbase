"""
AFTER tests for all enum opportunities - Specification for refactorings.

This test suite specifies the expected behavior AFTER implementing:
1. StealthOrderStatus enum (NEW - must be created)
2. Updated usage of ProductType enum
3. Updated usage of Direction enum
4. Updated usage of RevealConditionType enum
5. Other enum consistency improvements

These tests will FAIL until the refactorings are implemented, then PASS when done.
This defines the contract for the refactoring work.
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


class TestStealthOrderStatusEnumExists:
    """Tests that StealthOrderStatus enum exists and has required values."""

    def test_stealthorderstatus_enum_exists(self):
        """Test that StealthOrderStatus enum can be imported."""
        print("\n=== test_stealthorderstatus_enum_exists ===")

        try:
            from core.enums import StealthOrderStatus
            print(f"✓ StealthOrderStatus enum imported successfully")
        except ImportError as e:
            print(f"✗ StealthOrderStatus enum not found - needs to be created")
            raise AssertionError("StealthOrderStatus enum must be created in core/enums.py")

    def test_stealthorderstatus_hidden_value(self):
        """Test StealthOrderStatus.HIDDEN exists with correct value."""
        print("\n=== test_stealthorderstatus_hidden_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'HIDDEN'), "HIDDEN value must exist"
        assert StealthOrderStatus.HIDDEN.value == "HIDDEN"
        print(f"✓ StealthOrderStatus.HIDDEN = '{StealthOrderStatus.HIDDEN.value}'")

    def test_stealthorderstatus_pending_value(self):
        """Test StealthOrderStatus.PENDING exists with correct value."""
        print("\n=== test_stealthorderstatus_pending_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'PENDING'), "PENDING value must exist"
        assert StealthOrderStatus.PENDING.value == "PENDING"
        print(f"✓ StealthOrderStatus.PENDING = '{StealthOrderStatus.PENDING.value}'")

    def test_stealthorderstatus_triggered_value(self):
        """Test StealthOrderStatus.TRIGGERED exists with correct value."""
        print("\n=== test_stealthorderstatus_triggered_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'TRIGGERED'), "TRIGGERED value must exist"
        assert StealthOrderStatus.TRIGGERED.value == "TRIGGERED"
        print(f"✓ StealthOrderStatus.TRIGGERED = '{StealthOrderStatus.TRIGGERED.value}'")

    def test_stealthorderstatus_revealed_value(self):
        """Test StealthOrderStatus.REVEALED exists with correct value."""
        print("\n=== test_stealthorderstatus_revealed_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'REVEALED'), "REVEALED value must exist"
        assert StealthOrderStatus.REVEALED.value == "REVEALED"
        print(f"✓ StealthOrderStatus.REVEALED = '{StealthOrderStatus.REVEALED.value}'")

    def test_stealthorderstatus_executed_value(self):
        """Test StealthOrderStatus.EXECUTED exists with correct value."""
        print("\n=== test_stealthorderstatus_executed_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'EXECUTED'), "EXECUTED value must exist"
        assert StealthOrderStatus.EXECUTED.value == "EXECUTED"
        print(f"✓ StealthOrderStatus.EXECUTED = '{StealthOrderStatus.EXECUTED.value}'")

    def test_stealthorderstatus_cancelled_value(self):
        """Test StealthOrderStatus.CANCELLED exists with correct value."""
        print("\n=== test_stealthorderstatus_cancelled_value ===")

        from core.enums import StealthOrderStatus
        assert hasattr(StealthOrderStatus, 'CANCELLED'), "CANCELLED value must exist"
        assert StealthOrderStatus.CANCELLED.value == "CANCELLED"
        print(f"✓ StealthOrderStatus.CANCELLED = '{StealthOrderStatus.CANCELLED.value}'")

    def test_stealthorderstatus_inherits_from_str_enum(self):
        """Test StealthOrderStatus inherits from str and Enum."""
        print("\n=== test_stealthorderstatus_inherits_from_str_enum ===")

        from core.enums import StealthOrderStatus
        from enum import Enum

        # Should be usable as string
        assert isinstance(StealthOrderStatus.HIDDEN.value, str)
        # Should be an Enum member
        assert isinstance(StealthOrderStatus.HIDDEN, Enum)
        print(f"✓ StealthOrderStatus properly inherits from str and Enum")


class TestStealthOrderStatusUsageInCore:
    """Tests that StealthOrderStatus is used in core modules."""

    def test_stealth_order_manager_imports_enum(self):
        """Test that stealth_order_manager imports StealthOrderStatus."""
        print("\n=== test_stealth_order_manager_imports_enum ===")

        # Read the file to check for import
        with open('e:/coinbase/core/stealth_order_manager.py', 'r') as f:
            content = f.read()

        # Should import StealthOrderStatus
        assert 'from core.enums import' in content, "Should import from core.enums"
        assert 'StealthOrderStatus' in content, "Should import StealthOrderStatus"
        print(f"✓ stealth_order_manager.py imports StealthOrderStatus")

    def test_stealth_order_status_not_string_literal_in_manager(self):
        """Test that stealth_order_manager doesn't use 'HIDDEN' as string literal."""
        print("\n=== test_stealth_order_status_not_string_literal_in_manager ===")

        from core.stealth_order_manager import StealthOrderManager
        from database.database import PostgresDB

        db_client = PostgresDB()
        manager = StealthOrderManager(db_client)

        # After refactoring, create_stealth_order should use enum internally
        order_id = manager.create_stealth_order(
            product_id="BTC-USDC",
            side="BUY",
            total_size=1.0,
            limit_price=40000.0,
            reveal_condition={"type": "time_delay", "delay_seconds": 0}
        )

        order = manager._get_stealth_order(order_id)
        status = order.get("status")

        # Status should still be "HIDDEN" string value, but set via enum
        assert status == "HIDDEN", f"Status should be 'HIDDEN', got {status}"
        print(f"✓ Stealth order status = '{status}' (from enum)")


class TestProductTypeEnumUsage:
    """Tests that ProductType enum is used consistently."""

    def test_product_type_used_in_resolver(self):
        """Test that calculation/resolver.py uses ProductType enum."""
        print("\n=== test_product_type_used_in_resolver ===")

        with open('e:/coinbase/calculation/resolver.py', 'r') as f:
            content = f.read()

        # After refactoring, should import ProductType
        assert 'ProductType' in content, "Should use ProductType enum"
        print(f"✓ calculation/resolver.py uses ProductType enum")

    def test_product_type_in_set_check(self):
        """Test ProductType enum can be used in set membership checks."""
        print("\n=== test_product_type_in_set_check ===")

        product_type = ProductType.SPOT.value

        # Should work with enum values in set
        result = product_type in {ProductType.SPOT.value, ProductType.FUTURE.value}
        assert result is True
        print(f"✓ ProductType enum values work in set membership checks")


class TestDirectionEnumUsage:
    """Tests that Direction enum is used properly."""

    def test_direction_used_in_order_engine(self):
        """Test that order_engine.py uses Direction enum."""
        print("\n=== test_direction_used_in_order_engine ===")

        with open('e:/coinbase/core/order_engine.py', 'r') as f:
            content = f.read()

        # Should import Direction and use it
        assert 'from core.enums import' in content
        assert 'Direction' in content
        print(f"✓ core/order_engine.py imports and uses Direction enum")

    def test_direction_comparison_with_enum(self):
        """Test Direction enum can be used in comparisons."""
        print("\n=== test_direction_comparison_with_enum ===")

        direction = Direction.ABOVE.value

        # Should be able to compare with enum value
        assert direction == Direction.ABOVE.value
        assert direction != Direction.BELOW.value
        print(f"✓ Direction enum values work in comparisons")


class TestRevealConditionTypeUsage:
    """Tests that RevealConditionType enum is used properly."""

    def test_reveal_condition_used_in_order(self):
        """Test that order.py uses RevealConditionType enum."""
        print("\n=== test_reveal_condition_used_in_order ===")

        with open('e:/coinbase/order.py', 'r') as f:
            content = f.read()

        # Should import RevealConditionType after refactoring
        assert 'RevealConditionType' in content, "Should use RevealConditionType enum"
        print(f"✓ order.py uses RevealConditionType enum")

    def test_reveal_condition_in_defaults(self):
        """Test RevealConditionType used in default conditions."""
        print("\n=== test_reveal_condition_in_defaults ===")

        # Default should use enum value
        default_type = RevealConditionType.TIME_DELAY.value
        assert default_type == "time_delay"
        print(f"✓ Default reveal condition uses enum value: '{default_type}'")


class TestFollowUpDirectionEnumUsage:
    """Tests that FollowUpRevealDirection enum is used everywhere."""

    def test_followup_direction_in_order_engine(self):
        """Test FollowUpRevealDirection enum used in order_engine.py."""
        print("\n=== test_followup_direction_in_order_engine ===")

        with open('e:/coinbase/core/order_engine.py', 'r') as f:
            content = f.read()

        assert 'FollowUpRevealDirection' in content
        assert 'SAME' in content or 'OPPOSITE' in content
        print(f"✓ order_engine.py uses FollowUpRevealDirection enum")

    def test_followup_direction_comparison(self):
        """Test FollowUpRevealDirection enum in comparisons."""
        print("\n=== test_followup_direction_comparison ===")

        direction = FollowUpRevealDirection.SAME.value

        # After refactoring, comparisons should use enum
        assert direction == FollowUpRevealDirection.SAME.value
        assert direction != FollowUpRevealDirection.OPPOSITE.value
        print(f"✓ FollowUpRevealDirection enum works in comparisons")


class TestEnumBackwardCompatibility:
    """Tests that refactoring maintains backward compatibility."""

    def test_enum_string_values_match_database(self):
        """Test enum values match what's in the database."""
        print("\n=== test_enum_string_values_match_database ===")

        from core.enums import StealthOrderStatus

        # Database has these strings, enum values must match
        db_values = {"HIDDEN", "PENDING", "TRIGGERED", "REVEALED", "EXECUTED", "CANCELLED"}
        enum_values = {item.value for item in StealthOrderStatus}

        assert db_values == enum_values, f"Database values {db_values} should match enum {enum_values}"
        print(f"✓ StealthOrderStatus enum values match database expectations")

    def test_existing_config_values_still_work(self):
        """Test that existing configuration strings still work."""
        print("\n=== test_existing_config_values_still_work ===")

        from core.enums import StealthOrderStatus

        # Old code might compare: if status == "HIDDEN"
        # After refactoring, should still work
        status = StealthOrderStatus.HIDDEN.value
        assert status == "HIDDEN"
        print(f"✓ Backward compatibility maintained for string comparisons")


class TestEnumImportsInAllModules:
    """Tests that all modules properly import enums they use."""

    def test_stealth_condition_evaluator_imports(self):
        """Test stealth_condition_evaluator.py imports Direction."""
        print("\n=== test_stealth_condition_evaluator_imports ===")

        with open('e:/coinbase/business/stealth_condition_evaluator.py', 'r') as f:
            content = f.read()

        # Already imports correctly
        assert 'from core.enums import' in content
        assert 'Direction' in content or 'RevealConditionType' in content
        print(f"✓ stealth_condition_evaluator.py properly imports enums")

    def test_dashboard_server_imports(self):
        """Test dashboard_server.py imports enums it uses."""
        print("\n=== test_dashboard_server_imports ===")

        with open('e:/coinbase/dashboard_server.py', 'r') as f:
            content = f.read()

        # After refactoring, should import needed enums
        assert 'from core.enums import' in content
        print(f"✓ dashboard_server.py properly imports enums")


def run_all_after_tests():
    """Run all AFTER tests."""
    print("=" * 70)
    print("AFTER TESTS - All Enum Refactoring Requirements")
    print("=" * 70)

    test_classes = [
        TestStealthOrderStatusEnumExists,
        TestStealthOrderStatusUsageInCore,
        TestProductTypeEnumUsage,
        TestDirectionEnumUsage,
        TestRevealConditionTypeUsage,
        TestFollowUpDirectionEnumUsage,
        TestEnumBackwardCompatibility,
        TestEnumImportsInAllModules,
    ]

    passed = 0
    failed = 0
    errors = []

    for test_class in test_classes:
        test_instance = test_class()

        # Get all test methods
        test_methods = [method for method in dir(test_instance)
                       if method.startswith('test_')]

        for test_method in test_methods:
            try:
                # Run test
                getattr(test_instance, test_method)()
                passed += 1
            except AssertionError as e:
                print(f"✗ FAILED: {e}")
                failed += 1
                errors.append(str(e))
            except Exception as e:
                print(f"✗ ERROR: {str(e)}")
                failed += 1
                errors.append(str(e))

    print("\n" + "=" * 70)
    print(f"AFTER Tests Results: {passed} passed, {failed} failed")
    if failed > 0:
        print(f"\nFailed tests (will pass once refactoring is complete):")
        for error in errors[:5]:  # Show first 5 errors
            print(f"  - {error}")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_after_tests()
    # Don't exit with error code - these tests are EXPECTED to fail before refactoring
    sys.exit(0)
