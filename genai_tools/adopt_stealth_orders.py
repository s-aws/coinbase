#!/usr/bin/env python3
"""
Find and Adopt Orphaned Stealth Orders Tool

Searches for stealth orders that don't have a parent order reference, then finds
compatible parent orders from the order_parent table based on:
- Same product_id
- Same side (BUY/SELL)
- Price difference < threshold (default 0.5%)

This links orphaned stealth orders to valid parent orders in the trading system.

Usage:
    # Dry run - see what would be adopted
    python genai_tools/adopt_stealth_orders.py --dry-run

    # Actually adopt orphaned stealth orders
    python genai_tools/adopt_stealth_orders.py

    # Custom price tolerance
    python genai_tools/adopt_stealth_orders.py --tolerance 1.0

Examples:
    # Preview adoptions with 0.5% price tolerance
    python genai_tools/adopt_stealth_orders.py --dry-run --tolerance 0.5

    # Perform adoptions with 1% price tolerance
    python genai_tools/adopt_stealth_orders.py --tolerance 1.0

    # Show detailed results
    python genai_tools/adopt_stealth_orders.py --dry-run --detail
"""

import argparse
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Any, Dict
from database.order import adopt_orphaned_stealth_orders


def format_price(value: Any) -> str:
    """Format a price value for display."""
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.8f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return str(value)


def display_adoption_details(result: Dict[str, Any], tolerance: float) -> None:
    """Display detailed adoption results."""
    print("\n" + "=" * 100)
    print(f"[ADOPTION DETAILS] (Price tolerance: {tolerance}%)")
    print("=" * 100)

    if not result.get("details"):
        print("No adoption details to display")
        return

    # Group by status
    adopted = [d for d in result["details"] if d.get("status") == "ADOPTED"]
    dry_run = [d for d in result["details"] if d.get("status") == "DRY_RUN_WOULD_ADOPT"]
    skipped = [d for d in result["details"] if d.get("status") == "SKIPPED_NO_COMPATIBLE_PARENT"]
    failed = [d for d in result["details"] if d.get("status") == "ADOPTION_FAILED"]

    # Show adopted
    if adopted or dry_run:
        status_label = "WOULD ADOPT" if dry_run else "ADOPTED"
        details = dry_run or adopted
        print(f"\n[{status_label}] ({len(details)}):")
        print("-" * 100)
        for detail in details:
            print(f"  Stealth:     {detail.get('stealth_id')}")
            print(f"  Product:     {detail.get('product_id')}")
            print(f"  Side:        {detail.get('side')}")
            print(f"  Child Price: {format_price(detail.get('child_price'))}")
            print(f"  Parent ID:   {detail.get('parent_id')}")
            print(f"  Parent Price: {format_price(detail.get('parent_price'))}")
            print(f"  Price Diff:  {detail.get('price_diff_pct', 0):.4f}%")
            print()

    # Show skipped
    if skipped:
        print(f"\n[SKIPPED] ({len(skipped)}):")
        print("-" * 100)
        for detail in skipped:
            print(f"  Stealth: {detail.get('stealth_id')}")
            print(f"  Product: {detail.get('product_id')}")
            print(f"  Side:    {detail.get('side')}")
            print(f"  Price:   {format_price(detail.get('price'))}")
            print(f"  Reason:  {detail.get('reason')}")
            print()

    # Show failed
    if failed:
        print(f"\n[FAILED] ({len(failed)}):")
        print("-" * 100)
        for detail in failed:
            print(f"  Stealth: {detail.get('stealth_id')}")
            print(f"  Product: {detail.get('product_id')}")
            print(f"  Side:    {detail.get('side')}")
            print(f"  Reason:  {detail.get('reason')}")
            print()

    print("=" * 100)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Find and adopt orphaned stealth orders to compatible parent orders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Compatibility criteria:
  - Same product_id (e.g., BTC-USDC, BIP-20DEC30-CDE)
  - Same side (BUY or SELL)
  - Price difference < tolerance (default 0.5%)
  - Parent order must exist in order_parent table

Examples:
  # Preview with default 0.5% tolerance
  python genai_tools/adopt_stealth_orders.py --dry-run

  # Preview with 1% tolerance
  python genai_tools/adopt_stealth_orders.py --dry-run --tolerance 1.0

  # Perform adoptions with 0.5% tolerance
  python genai_tools/adopt_stealth_orders.py

  # Perform adoptions with 2% tolerance
  python genai_tools/adopt_stealth_orders.py --tolerance 2.0

  # Show detailed results
  python genai_tools/adopt_stealth_orders.py --dry-run --detail
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be adopted without making changes"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        help="Maximum price difference as %% of parent price (default 0.5%%)"
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed adoption information"
    )

    args = parser.parse_args()

    # Validate tolerance
    if args.tolerance < 0:
        print(f"[ERROR] Tolerance must be non-negative, got {args.tolerance}")
        return 1

    # Run adoption
    print(f"\n[INFO] Finding orphaned stealth orders...")
    print(f"   Price tolerance: {args.tolerance}%")
    print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    result = adopt_orphaned_stealth_orders(
        price_tolerance_pct=args.tolerance,
        dry_run=args.dry_run
    )

    # Show details if requested
    if args.detail:
        display_adoption_details(result, args.tolerance)

    # Show summary
    print()
    print(f"[SUMMARY]:")
    print(f"   Total stealth orders:       {result.get('total_stealth_orders', 0)}")
    print(f"   Orphaned found:             {result.get('orphaned_found', 0)}")
    print(f"   Parent orders available:    {result.get('parent_orders_available', 0)}")
    print(f"   Adoptions completed:        {result.get('adoptions_completed', 0)}")
    print(f"   Adoptions skipped:          {result.get('adoptions_skipped', 0)}")

    if result.get("error"):
        print(f"\n[ERROR] {result.get('error')}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
