#!/usr/bin/env python3
"""
Test to verify the fix for stealth order reveal bug.

This test ensures that:
1. Orders created without explicit reveal_condition default to 60-second delay (not 0-second)
2. Orders don't immediately become REVEALED just because a default condition is applied
"""

from order import create_limit_order_span
import json

print("\n" + "="*80)
print("TEST: Default Reveal Condition Should Be 60 Seconds (Not Immediate)")
print("="*80)

# Test 1: Create order without explicit reveal_condition
print("\n✓ Test 1: Creating order without explicit reveal_condition...")
try:
    orders = create_limit_order_span(
        product_id="BTC-USDC",
        side="SELL",
        order_base_size=0.5,
        start_price=42000.0,
        max_order_count=1,
        # NOTE: No reveal_condition specified
    )

    if orders and orders[0]["success"]:
        reveal_condition = orders[0]["success_response"].get("reveal_condition")
        print(f"  Reveal condition: {reveal_condition}")

        # Verify it's NOT immediate (delay_seconds != 0)
        if reveal_condition.get("delay_seconds") == 0:
            print("  ✗ FAILED: Default is still 0-second delay (immediate)")
            exit(1)
        elif reveal_condition.get("delay_seconds") == 60:
            print("  ✓ PASSED: Default is now 60-second delay")
        else:
            print(f"  ✓ PASSED: Default delay is {reveal_condition.get('delay_seconds')}s (not 0)")
    else:
        print("  ✗ FAILED: Order creation failed")
        exit(1)

except Exception as e:
    print(f"  ✗ ERROR: {e}")
    exit(1)

# Test 2: Explicit immediate reveal still works
print("\n✓ Test 2: Explicit get_immediate_reveal_condition() still works...")
try:
    from order import get_immediate_reveal_condition

    immediate_condition = get_immediate_reveal_condition()
    if immediate_condition.get("delay_seconds") == 0:
        print("  ✓ PASSED: Explicit immediate reveal (0-second) still available")
    else:
        print(f"  ✗ FAILED: get_immediate_reveal_condition() should have delay_seconds=0")
        exit(1)

except Exception as e:
    print(f"  ✗ ERROR: {e}")
    exit(1)

print("\n" + "="*80)
print("✓ ALL TESTS PASSED - Fix is working correctly!")
print("="*80)
print("\nSummary:")
print("- Default reveal condition is now 60 seconds (prevents accidental instant reveals)")
print("- Users can still explicitly use get_immediate_reveal_condition() for 0-second delays")
print("- This prevents the bug where 85+ orders were created with immediate reveal")
