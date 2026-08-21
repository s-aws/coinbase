#!/usr/bin/env python3
"""
Child Order Adoption Tool

Allows reassigning a child order to a different parent order (adoption).
This is useful for rebalancing strategies where orders need to be reorganized
without losing historical context.

The adoption preserves audit trail information:
- Previous parent ID is stored for reference
- Adoption timestamp is recorded
- Both database and in-memory structures are updated atomically

Usage:
    python genai_tools/adopt_child_order.py \\
        --child <child_order_id> \\
        --new-parent <new_parent_order_id> \\
        [--keep-history]

Examples:
    # Show current parent
    python genai_tools/adopt_child_order.py --show-parent <child_order_id>

    # Adopt child-uuid-1 to parent-uuid-2, keeping history
    python genai_tools/adopt_child_order.py \\
        --child 123e4567-e89b-12d3-a456-426614174000 \\
        --new-parent 123e4567-e89b-12d3-a456-426614174111 \\
        --keep-history

    # Adopt without keeping history (old parent link lost)
    python genai_tools/adopt_child_order.py \\
        --child 123e4567-e89b-12d3-a456-426614174000 \\
        --new-parent 123e4567-e89b-12d3-a456-426614174111

    # Show current parent of a child order
    python genai_tools/adopt_child_order.py --show-parent <child_order_id>

Features:
    - Atomic updates (database + in-memory)
    - Audit trail preservation (previous parent tracking)
    - Validation before adoption
    - Safe to run (validates orders exist first)
"""

import argparse
import sys
from typing import Optional
from database.database import PostgresDB
from database.order import adopt_child_to_parent, get_child_orders

DB_CLIENT: PostgresDB = PostgresDB()


def get_child_parent(child_client_order_id: str) -> Optional[str]:
    """Get the current parent of a child order.

    Args:
        child_client_order_id: The child order UUID.

    Returns:
        Parent client_order_id if found, None otherwise.
    """
    query = "SELECT parent_client_order_id FROM order_child WHERE client_order_id = %s"
    try:
        result = DB_CLIENT.execute_query(query, (child_client_order_id,))
        if result:
            return result[0].get("parent_client_order_id")
        return None
    except Exception as e:
        print(f"❌ Error querying child order: {e}")
        return None


def get_child_info(child_client_order_id: str) -> Optional[dict]:
    """Get full information about a child order.

    Args:
        child_client_order_id: The child order UUID.

    Returns:
        Dict with order info if found, None otherwise.
    """
    query = """
    SELECT
        client_order_id,
        parent_client_order_id,
        previous_parent_client_order_id,
        adopted_at,
        product_id,
        side,
        size,
        price,
        status,
        created_at
    FROM order_child
    WHERE client_order_id = %s
    """
    try:
        result = DB_CLIENT.execute_query(query, (child_client_order_id,))
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"❌ Error querying child order: {e}")
        return None


def get_parent_info(parent_client_order_id: str) -> Optional[dict]:
    """Get full information about a parent order.

    Args:
        parent_client_order_id: The parent order UUID.

    Returns:
        Dict with order info if found, None otherwise.
    """
    query = """
    SELECT
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
        target_movement,
        target_movement_type,
        max_order_replacement,
        current_order_replacement,
        created_at
    FROM order_parent
    WHERE client_order_id = %s
    """
    try:
        result = DB_CLIENT.execute_query(query, (parent_client_order_id,))
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"❌ Error querying parent order: {e}")
        return None


def display_order_info(label: str, order_info: dict) -> None:
    """Pretty print order information.

    Args:
        label: Label for the order (e.g., "Current Parent", "New Parent")
        order_info: Order dict with fields.
    """
    if not order_info:
        print(f"  {label}: (not found)")
        return

    print(f"  {label}:")
    for key, value in order_info.items():
        # Skip internal fields
        if key in ("id",):
            continue
        # Format values
        if value is None:
            value_str = "(null)"
        elif isinstance(value, str) and len(str(value)) > 50:
            value_str = f"{str(value)[:50]}..."
        else:
            value_str = str(value)

        print(f"    {key:<30} {value_str}")


def show_adoption_path(child_client_order_id: str) -> None:
    """Show the adoption path of a child order.

    Args:
        child_client_order_id: The child order UUID.
    """
    child_info = get_child_info(child_client_order_id)
    if not child_info:
        print(f"❌ Child order not found: {child_client_order_id}")
        return

    print(f"\n📋 Adoption Path for {child_client_order_id}")
    print("=" * 80)

    current_parent = child_info.get("parent_client_order_id")
    previous_parent = child_info.get("previous_parent_client_order_id")
    adopted_at = child_info.get("adopted_at")

    print(f"Child Order: {child_client_order_id}")

    if previous_parent:
        print(f"\n  Original Parent: {previous_parent}")
        original_parent_info = get_parent_info(previous_parent)
        display_order_info("Original Parent Info", original_parent_info)

    if adopted_at:
        print(f"\n  Adopted At: {adopted_at}")

    print(f"\n  Current Parent: {current_parent}")
    current_parent_info = get_parent_info(current_parent)
    display_order_info("Current Parent Info", current_parent_info)

    print("\n" + "=" * 80)


def show_child_parent(child_client_order_id: str) -> None:
    """Show the current parent of a child order.

    Args:
        child_client_order_id: The child order UUID.
    """
    parent_id = get_child_parent(child_client_order_id)
    if parent_id:
        print(f"✅ Child {child_client_order_id} is linked to parent {parent_id}")
        show_adoption_path(child_client_order_id)
    else:
        print(f"❌ Child order not found: {child_client_order_id}")


def perform_adoption(
    child_client_order_id: str,
    new_parent_client_order_id: str,
    keep_history: bool = True
) -> None:
    """Perform the adoption.

    Args:
        child_client_order_id: The child order UUID.
        new_parent_client_order_id: The new parent order UUID.
        keep_history: Whether to keep adoption history.
    """
    print(f"\n📦 Adopting child order...")
    print("=" * 80)
    print(f"Child: {child_client_order_id}")
    print(f"New Parent: {new_parent_client_order_id}")
    print(f"Keep History: {keep_history}")
    print("=" * 80)

    # Show current state
    child_info = get_child_info(child_client_order_id)
    if not child_info:
        print(f"❌ Child order not found: {child_client_order_id}")
        return

    old_parent = child_info.get("parent_client_order_id")
    print(f"\n📍 Current State:")
    print(f"  Child's current parent: {old_parent}")

    new_parent_info = get_parent_info(new_parent_client_order_id)
    if not new_parent_info:
        print(f"❌ New parent order not found: {new_parent_client_order_id}")
        return

    print(f"  New parent exists: ✅")

    # Perform adoption
    print(f"\n🔄 Performing adoption...")
    success = adopt_child_to_parent(
        child_client_order_id=child_client_order_id,
        new_parent_client_order_id=new_parent_client_order_id,
        keep_adoption_history=keep_history,
    )

    if success:
        print(f"✅ Adoption successful!")
        print(f"\n📍 New State:")
        updated_child_info = get_child_info(child_client_order_id)
        if updated_child_info:
            print(f"  Child's parent: {updated_child_info.get('parent_client_order_id')}")
            if keep_history and updated_child_info.get('previous_parent_client_order_id'):
                print(f"  Previous parent (history): {updated_child_info.get('previous_parent_client_order_id')}")
                print(f"  Adopted at: {updated_child_info.get('adopted_at')}")
        show_adoption_path(child_client_order_id)
    else:
        print(f"❌ Adoption failed - check error messages above")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage child order adoption to different parents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Adopt with history tracking
  python genai_tools/adopt_child_order.py \\
      --child abc123 --new-parent def456 --keep-history

  # Show current parent
  python genai_tools/adopt_child_order.py --show-parent abc123

  # Show full adoption path
  python genai_tools/adopt_child_order.py --path abc123
        """
    )

    parser.add_argument(
        "--child",
        type=str,
        help="Child order UUID to adopt"
    )
    parser.add_argument(
        "--new-parent",
        type=str,
        help="New parent order UUID"
    )
    parser.add_argument(
        "--keep-history",
        action="store_true",
        default=True,
        help="Keep adoption history (default: True)"
    )
    parser.add_argument(
        "--show-parent",
        type=str,
        metavar="CHILD_ID",
        help="Show current parent of a child order"
    )
    parser.add_argument(
        "--path",
        type=str,
        metavar="CHILD_ID",
        help="Show full adoption path"
    )

    args = parser.parse_args()

    # Show parent
    if args.show_parent:
        show_child_parent(args.show_parent)
        return

    # Show path
    if args.path:
        show_adoption_path(args.path)
        return

    # Perform adoption
    if args.child and args.new_parent:
        perform_adoption(
            child_client_order_id=args.child,
            new_parent_client_order_id=args.new_parent,
            keep_history=args.keep_history,
        )
        return

    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()
