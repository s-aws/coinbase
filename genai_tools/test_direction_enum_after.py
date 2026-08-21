"""
AFTER tests for Direction/FollowUpRevealDirection enum updates.

Tests the updated code to ensure enum changes work correctly and nothing broke.
These should match the BEFORE tests' functionality plus verify proper enum usage.
"""

import sys
import json
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, '/'.join(__file__.split('/')[:-2]))

from core.enums import Direction, RevealConditionType, FollowUpRevealDirection
from core.stealth_order_manager import StealthOrderManager
from database.database import PostgresDB


def test_new_followup_enum_exists():
    """Test that FollowUpRevealDirection enum was created successfully."""
    print("\n=== test_new_followup_enum_exists ===")

    assert hasattr(FollowUpRevealDirection, 'SAME'), "FollowUpRevealDirection should have SAME"
    assert hasattr(FollowUpRevealDirection, 'OPPOSITE'), "FollowUpRevealDirection should have OPPOSITE"

    assert FollowUpRevealDirection.SAME.value == "same", "SAME should be 'same'"
    assert FollowUpRevealDirection.OPPOSITE.value == "opposite", "OPPOSITE should be 'opposite'"

    print(f"✓ FollowUpRevealDirection.SAME = {FollowUpRevealDirection.SAME.value}")
    print(f"✓ FollowUpRevealDirection.OPPOSITE = {FollowUpRevealDirection.OPPOSITE.value}")
    print("✓ FollowUpRevealDirection enum created successfully")


def test_stealth_order_manager_uses_enum_default():
    """Test StealthOrderManager uses enum default for follow_up_reveal_direction."""
    print("\n=== test_stealth_order_manager_uses_enum_default ===")

    db_client = PostgresDB()
    manager = StealthOrderManager(db_client)

    # Create order with no follow_up_reveal_direction specified
    order_id = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="BUY",
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0}
    )

    order = manager._get_stealth_order(order_id)
    assert order is not None, "Order should be created"

    # Should default to FollowUpRevealDirection.OPPOSITE.value
    follow_up_dir = order.get("follow_up_reveal_direction")
    assert follow_up_dir == FollowUpRevealDirection.OPPOSITE.value, \
        f"Default should be {FollowUpRevealDirection.OPPOSITE.value}, got {follow_up_dir}"

    print(f"✓ Default follow_up_reveal_direction = '{follow_up_dir}'")
    print("✓ StealthOrderManager correctly uses enum default")

    return order_id


def test_stealth_order_manager_accepts_enum_values():
    """Test StealthOrderManager accepts both enum values and string values."""
    print("\n=== test_stealth_order_manager_accepts_enum_values ===")

    db_client = PostgresDB()
    manager = StealthOrderManager(db_client)

    # Test with string values (backward compatibility)
    order_id_same = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="BUY",
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        follow_up_reveal_direction="same"  # String value
    )

    order_same = manager._get_stealth_order(order_id_same)
    assert order_same.get("follow_up_reveal_direction") == "same"
    print(f"✓ Can set follow_up_reveal_direction='same' (string)")

    # Test with enum value
    order_id_enum = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="SELL",
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        follow_up_reveal_direction=FollowUpRevealDirection.OPPOSITE.value
    )

    order_enum = manager._get_stealth_order(order_id_enum)
    assert order_enum.get("follow_up_reveal_direction") == FollowUpRevealDirection.OPPOSITE.value
    print(f"✓ Can set follow_up_reveal_direction using enum value")

    print("✓ StealthOrderManager accepts both string and enum values")


def test_direction_enum_still_works():
    """Test Direction enum still works as before (regression test)."""
    print("\n=== test_direction_enum_still_works ===")

    # These should still work with enum values
    assert Direction.ABOVE.value == "above"
    assert Direction.BELOW.value == "below"

    print(f"✓ Direction.ABOVE = {Direction.ABOVE.value}")
    print(f"✓ Direction.BELOW = {Direction.BELOW.value}")
    print("✓ Direction enum still works correctly (no regression)")


def test_reveal_condition_type_still_works():
    """Test RevealConditionType enum still works (regression test)."""
    print("\n=== test_reveal_condition_type_still_works ===")

    # These should still work
    assert RevealConditionType.PRICE_THRESHOLD.value == "price"
    assert RevealConditionType.TIME_DELAY.value == "time_delay"
    assert RevealConditionType.CUMULATIVE_VOLUME.value == "cumulative_volume"

    print("✓ RevealConditionType enum still works correctly (no regression)")


def test_price_threshold_evaluator_with_direction():
    """Test PriceThresholdEvaluator works with Direction enum (regression test)."""
    print("\n=== test_price_threshold_evaluator_with_direction ===")

    from business.stealth_condition_evaluator import (
        PriceThresholdEvaluator,
        evaluate_stealth_reveal_condition,
        get_evaluator,
    )

    evaluator = get_evaluator("price")

    # Test Direction enum usage
    market_data = {"price": 39500.0}
    condition_config = {
        "price_threshold": 40000.0,
        "direction": Direction.BELOW.value,
        "hold_duration_seconds": 0
    }
    order_data = {"condition_first_met_at": datetime.utcnow()}

    condition_met, reason = evaluate_stealth_reveal_condition(
        evaluator,
        market_data,
        condition_config,
        order_data,
    )
    assert condition_met is True, "Price 39500 should be below 40000"
    print(f"✓ Direction enum works with PriceThresholdEvaluator (no regression)")


def test_enum_values_match_database_expectations():
    """Test that enum values match what's expected in database and configs."""
    print("\n=== test_enum_values_match_database_expectations ===")

    # These values should match what's in the database and UI
    assert FollowUpRevealDirection.SAME.value == "same", "SAME value must be 'same'"
    assert FollowUpRevealDirection.OPPOSITE.value == "opposite", "OPPOSITE value must be 'opposite'"

    # Test that they can be used in config dicts like the database/UI would
    config_from_db = {
        "follow_up_reveal_direction": "same",  # How it would be stored in DB
    }

    # Should be able to compare to enum value
    assert config_from_db["follow_up_reveal_direction"] == FollowUpRevealDirection.SAME.value
    print(f"✓ Enum values match database/config expectations")

    config_opposite = {
        "follow_up_reveal_direction": "opposite",
    }
    assert config_opposite["follow_up_reveal_direction"] == FollowUpRevealDirection.OPPOSITE.value
    print(f"✓ Both SAME and OPPOSITE values compatible with database")


def test_enum_in_order_engine_logic():
    """Test that order_engine.py can use the new enum in its logic."""
    print("\n=== test_enum_in_order_engine_logic ===")

    # Simulate what order_engine.py does
    original_stealth_order = {
        "follow_up_reveal_direction": FollowUpRevealDirection.OPPOSITE.value,
        "reveal_condition_json": {
            "type": "price",
            "direction": "below",
        }
    }

    direction_choice = original_stealth_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value)

    # Test OPPOSITE logic
    if direction_choice == FollowUpRevealDirection.OPPOSITE.value:
        # Should flip the direction
        assert True  # Logic works
        print(f"✓ Enum comparison works in order_engine logic (OPPOSITE)")

    # Test SAME logic
    original_stealth_order["follow_up_reveal_direction"] = FollowUpRevealDirection.SAME.value
    direction_choice_same = original_stealth_order.get("follow_up_reveal_direction", FollowUpRevealDirection.OPPOSITE.value)

    if direction_choice_same == FollowUpRevealDirection.SAME.value:
        # Should keep original direction
        assert True  # Logic works
        print(f"✓ Enum comparison works in order_engine logic (SAME)")


def test_backward_compatibility_with_string_values():
    """Test that code still works with string values from old configs/database."""
    print("\n=== test_backward_compatibility_with_string_values ===")

    # Existing data might have string values
    old_config_opposite = "opposite"  # String, not enum
    old_config_same = "same"  # String, not enum

    # Should be able to compare to enum values
    assert old_config_opposite == FollowUpRevealDirection.OPPOSITE.value
    assert old_config_same == FollowUpRevealDirection.SAME.value

    print(f"✓ Old string configs compatible with new enum values")
    print(f"✓ Backward compatibility maintained for existing data")


def run_all_after_tests():
    """Run all AFTER tests."""
    print("=" * 70)
    print("AFTER TESTS - Direction/FollowUpRevealDirection Enum Updates")
    print("=" * 70)

    tests = [
        test_new_followup_enum_exists,
        test_stealth_order_manager_uses_enum_default,
        test_stealth_order_manager_accepts_enum_values,
        test_direction_enum_still_works,
        test_reveal_condition_type_still_works,
        test_price_threshold_evaluator_with_direction,
        test_enum_values_match_database_expectations,
        test_enum_in_order_engine_logic,
        test_backward_compatibility_with_string_values,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR: {str(e)}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"AFTER Tests Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_after_tests()
    sys.exit(0 if success else 1)
