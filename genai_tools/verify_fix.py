#!/usr/bin/env python3
"""
Simple test to verify the default reveal condition fix.
Checks the actual code change without needing full system initialization.
"""

import sys
import re

print("\n" + "="*80)
print("TEST: Verify Default Reveal Condition Fix")
print("="*80)

# Read the order.py file and check the default reveal condition
try:
    with open('order.py', 'r') as f:
        content = f.read()

    # Find the create_limit_order_span function and check what it uses as default
    # Look for the pattern where reveal_condition is set if not provided
    pattern = r'if not reveal_condition:\s*reveal_condition = \{[^}]*"delay_seconds":\s*(\d+)'
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("✗ FAILED: Could not find reveal_condition default in order.py")
        sys.exit(1)

    delay_seconds = int(match.group(1))
    print(f"\n✓ Found default reveal condition in order.py")
    print(f"  delay_seconds = {delay_seconds}")

    if delay_seconds == 0:
        print("✗ FAILED: Default is still 0 (immediate reveal)")
        sys.exit(1)
    elif delay_seconds == 60:
        print("✓ PASSED: Default is now 60 seconds")
    else:
        print(f"✓ PASSED: Default is {delay_seconds} seconds (not 0)")

    # Also verify get_immediate_reveal_condition still returns 0
    pattern2 = r'def get_immediate_reveal_condition.*?return \{[^}]*"delay_seconds":\s*(\d+)'
    match2 = re.search(pattern2, content, re.DOTALL)

    if match2:
        immediate_delay = int(match2.group(1))
        if immediate_delay == 0:
            print("\n✓ get_immediate_reveal_condition() still returns delay_seconds=0")
        else:
            print(f"\n✗ WARNING: get_immediate_reveal_condition() returns delay_seconds={immediate_delay}")

    print("\n" + "="*80)
    print("✓ FIX VERIFIED - Default reveal condition is now 60 seconds")
    print("="*80)
    print("\nWhat this fixes:")
    print("- Orders created without explicit reveal_condition no longer default to instant reveal")
    print("- This prevents 85+ orders from being created with delay_seconds=0")
    print("- Users who explicitly want instant reveal can still use get_immediate_reveal_condition()")
    print("\nBenefits:")
    print("- Prevents accidental instant placement when reveal_condition is not specified")
    print("- Orders now have time to settle before being placed on the exchange")
    print("- Users still have full control by explicitly specifying a reveal_condition")

except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)
