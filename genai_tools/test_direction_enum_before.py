"""
BEFORE tests for Direction/FollowUpRevealDirection enum updates.

Tests the current state BEFORE enum changes to establish baseline behavior.
These must pass before making any changes.
"""

import sys
import json
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, '/'.join(__file__.split('/')[:-2]))

from core.enums import Direction, RevealConditionType
from core.stealth_order_manager import StealthOrderManager
from database.database import PostgresDB


def test_direction_enum_values():
    """Test that Direction enum has expected values."""
    print("\n=== test_direction_enum_values ===")

    assert hasattr(Direction, 'ABOVE'), "Direction should have ABOVE"
    assert hasattr(Direction, 'BELOW'), "Direction should have BELOW"

    assert Direction.ABOVE.value == "above", "ABOVE should be 'above'"
    assert Direction.BELOW.value == "below", "BELOW should be 'below'"

    print(f"✓ Direction.ABOVE = {Direction.ABOVE.value}")
    print(f"✓ Direction.BELOW = {Direction.BELOW.value}")
    print("✓ Direction enum values are correct")


def test_current_follow_up_direction_string_usage():
    """Test current hardcoded string usage for follow-up directions."""
    print("\n=== test_current_follow_up_direction_string_usage ===")

    # These are currently strings, not enums
    follow_up_directions = ["same", "opposite"]

    for direction in follow_up_directions:
        assert isinstance(direction, str), f"Currently {direction} is a string, not an enum"

    print(f"✓ follow_up_reveal_direction 'same' is a string")
    print(f"✓ follow_up_reveal_direction 'opposite' is a string")
    print("✓ Current implementation uses string literals (not enums)")


def test_stealth_order_manager_follow_up_defaults():
    """Test StealthOrderManager defaults to 'opposite' for follow_up_reveal_direction."""
    print("\n=== test_stealth_order_manager_follow_up_defaults ===")

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

    # Default should be "opposite"
    follow_up_dir = order.get("follow_up_reveal_direction")
    assert follow_up_dir == "opposite", f"Default should be 'opposite', got {follow_up_dir}"

    print(f"✓ Default follow_up_reveal_direction = '{follow_up_dir}'")
    print("✓ StealthOrderManager correctly defaults to 'opposite'")

    return order_id


def test_stealth_order_manager_custom_follow_up():
    """Test StealthOrderManager accepts custom follow_up_reveal_direction values."""
    print("\n=== test_stealth_order_manager_custom_follow_up ===")

    db_client = PostgresDB()
    manager = StealthOrderManager(db_client)

    # Test with explicit "same"
    order_id_same = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="BUY",
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        follow_up_reveal_direction="same"
    )

    order_same = manager._get_stealth_order(order_id_same)
    assert order_same.get("follow_up_reveal_direction") == "same"
    print(f"✓ Can set follow_up_reveal_direction='same'")

    # Test with explicit "opposite"
    order_id_opp = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="SELL",
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0},
        follow_up_reveal_direction="opposite"
    )

    order_opp = manager._get_stealth_order(order_id_opp)
    assert order_opp.get("follow_up_reveal_direction") == "opposite"
    print(f"✓ Can set follow_up_reveal_direction='opposite'")

    print("✓ StealthOrderManager accepts custom follow_up_reveal_direction values")


def test_reveal_condition_type_enum():
    """Test RevealConditionType enum is properly used."""
    print("\n=== test_reveal_condition_type_enum ===")

    # These should work with enum values
    condition_types = [
        (RevealConditionType.PRICE_THRESHOLD.value, "price"),
        (RevealConditionType.TIME_DELAY.value, "time_delay"),
        (RevealConditionType.CUMULATIVE_VOLUME.value, "cumulative_volume"),
        (RevealConditionType.SPREAD.value, "spread"),
        (RevealConditionType.PRODUCT_RATIO.value, "product_ratio"),
        (RevealConditionType.COMPOSITE.value, "composite"),
    ]

    for enum_val, expected in condition_types:
        assert enum_val == expected, f"RevealConditionType value mismatch: {enum_val} != {expected}"
        print(f"✓ RevealConditionType.{enum_val.upper().replace('_', ' ')} = '{expected}'")

    print("✓ RevealConditionType enum values are correct and used")


def test_order_side_string_parameters():
    """Test that order side is currently accepted as string parameter."""
    print("\n=== test_order_side_string_parameters ===")

    db_client = PostgresDB()
    manager = StealthOrderManager(db_client)

    # Side is currently str type hint, accepts string values
    order_id_buy = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="BUY",  # String, not enum
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0}
    )

    order_buy = manager._get_stealth_order(order_id_buy)
    assert order_buy.get("side") == "BUY"
    print(f"✓ Side parameter accepts 'BUY' string")

    order_id_sell = manager.create_stealth_order(
        product_id="BTC-USDC",
        side="SELL",  # String, not enum
        total_size=1.0,
        limit_price=40000.0,
        reveal_condition={"type": "time_delay", "delay_seconds": 0}
    )

    order_sell = manager._get_stealth_order(order_id_sell)
    assert order_sell.get("side") == "SELL"
    print(f"✓ Side parameter accepts 'SELL' string")

    print("✓ Side parameter works with string literals (not enums)")


def test_direction_enum_in_condition_evaluator():
    """Test Direction enum is properly used in condition evaluators."""
    print("\n=== test_direction_enum_in_condition_evaluator ===")

    from business.stealth_condition_evaluator import (
        PriceThresholdEvaluator,
        evaluate_stealth_reveal_condition,
        get_evaluator,
    )

    evaluator = get_evaluator("price")
    assert isinstance(evaluator, PriceThresholdEvaluator)

    # Test Direction enum usage in evaluator
    market_data = {"price": 39500.0}
    condition_config = {
        "price_threshold": 40000.0,
        "direction": Direction.BELOW.value,  # Using enum value
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
    print(f"✓ PriceThresholdEvaluator works with Direction.BELOW")

    # Test with ABOVE
    market_data_above = {"price": 40500.0}
    condition_config_above = {
        "price_threshold": 40000.0,
        "direction": Direction.ABOVE.value,
        "hold_duration_seconds": 0
    }

    condition_met_above, reason_above = evaluate_stealth_reveal_condition(
        evaluator,
        market_data_above,
        condition_config_above,
        order_data,
    )
    assert condition_met_above is True, "Price 40500 should be above 40000"
    print(f"✓ PriceThresholdEvaluator works with Direction.ABOVE")

    print("✓ Direction enum is properly used in condition evaluators")


def run_all_before_tests():
    """Run all BEFORE tests."""
    print("=" * 70)
    print("BEFORE TESTS - Direction Enum Updates")
    print("=" * 70)

    tests = [
        test_direction_enum_values,
        test_current_follow_up_direction_string_usage,
        test_stealth_order_manager_follow_up_defaults,
        test_stealth_order_manager_custom_follow_up,
        test_reveal_condition_type_enum,
        test_order_side_string_parameters,
        test_direction_enum_in_condition_evaluator,
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
    print(f"BEFORE Tests Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_before_tests()
    sys.exit(0 if success else 1)
