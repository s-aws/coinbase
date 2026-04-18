"""
CLI tool for retrieving parent orders and their linked child orders.

This tool provides a user-friendly interface to query the database and view
parent-child order relationships. Unlike simple helper scripts, this is a proper
CLI tool with argument parsing and multiple query options.

Usage:
    python cli_parent_child_orders.py                    # List all parent orders with children
    python cli_parent_child_orders.py --parent ORDER_ID  # Show specific parent order and its children
    python cli_parent_child_orders.py --status FILLED    # Filter by status
    python cli_parent_child_orders.py --help              # Show all options

Features:
    - List all parent orders or filter by ID
    - Show linked child orders for each parent
    - Filter by order status
    - Pretty-printed table format
    - Uses project credentials (COINBASE_API_KEY, COINBASE_API_SECRET)
"""

import argparse
import sys
from typing import List, Dict, Any, Optional
from database.database import PostgresDB
from database.order import get_parent_orders, get_parent_order, get_child_orders
from tabulate import tabulate


class ParentChildOrdersCLI:
    """CLI interface for querying parent-child order relationships."""
    
    def __init__(self):
        """Initialize the CLI with database connection."""
        self.db = PostgresDB()
        # Detect if we can use emoji (not Windows CP1252)
        self.use_emoji = sys.stdout.encoding.lower() not in ('cp1252', 'ascii')
    
    def format_numeric(self, value: Any) -> str:
        """Format numeric values for display.
        
        Args:
            value: The value to format (could be None, string, or number).
        
        Returns:
            Formatted string representation.
        """
        if value is None or value == "":
            return "—"
        try:
            float_val = float(value)
            # Use up to 8 decimal places, but strip trailing zeros
            return f"{float_val:.8f}".rstrip('0').rstrip('.')
        except (ValueError, TypeError):
            return str(value)
    
    def get_parent_orders_data(
        self,
        parent_id: Optional[str] = None,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch parent orders, optionally filtered.
        
        Args:
            parent_id: If provided, fetch only this parent order.
            status_filter: If provided, filter by status (case-insensitive).
        
        Returns:
            List of parent order dictionaries.
        """
        if parent_id:
            order = get_parent_order(parent_id)
            if not order:
                emoji = "x" if self.use_emoji else "!"
                print(f"[{emoji}] Parent order not found: {parent_id}")
                return []
            parents = [order]
        else:
            parents = get_parent_orders()
        
        # Filter by status if provided
        if status_filter:
            status_upper = status_filter.upper()
            parents = [p for p in parents if p.get("status", "").upper() == status_upper]
        
        return parents
    
    def get_children_for_parent(self, parent_id: str) -> List[Dict[str, Any]]:
        """Fetch all child orders for a parent.
        
        Args:
            parent_id: The parent order's client_order_id.
        
        Returns:
            List of child order dictionaries.
        """
        return get_child_orders(parent_id)
    
    def display_parent_order(self, parent: Dict[str, Any]) -> None:
        """Display a single parent order with its children.
        
        Args:
            parent: Parent order dictionary.
        """
        parent_id = parent.get("client_order_id")
        emoji = "[P]" if self.use_emoji else "[P]"
        
        # Prepare parent order display
        parent_data = {
            "Client Order ID": parent_id,
            "Product ID": parent.get("product_id", "—"),
            "Side": parent.get("side", "—"),
            "Size": self.format_numeric(parent.get("size")),
            "Price": self.format_numeric(parent.get("price")),
            "Target Movement": (
                f"{self.format_numeric(parent.get('target_movement'))} "
                f"({parent.get('target_movement_type', '?')})"
            ),
            "Status": parent.get("status", "—").upper(),
            "Max Replacements": parent.get("max_order_replacement", 0),
            "Current Replacements": parent.get("current_order_replacement", 0),
            "Created At": parent.get("created_at", "—"),
        }
        
        print("\n" + "="*80)
        print(f"{emoji} PARENT ORDER")
        print("="*80)
        for key, value in parent_data.items():
            print(f"  {key:<25} {value}")
        
        # Fetch and display child orders
        children = self.get_children_for_parent(parent_id)
        
        if not children:
            print(f"\n  [i] No child orders linked to this parent")
        else:
            # Sort children by creation date (newest first - descending)
            children_sorted = sorted(
                children,
                key=lambda x: x.get("created_at", ""),
                reverse=True
            )
            
            print(f"\n  [C] CHILD ORDERS ({len(children_sorted)} total):")
            print("  " + "-"*76)
            
            child_rows = []
            for child in children_sorted:
                child_rows.append([
                    child.get("client_order_id", "—"),
                    child.get("product_id", "—"),
                    child.get("side", "—"),
                    self.format_numeric(child.get("size")),
                    self.format_numeric(child.get("price")),
                    child.get("status", "—").upper(),
                    child.get("created_at", "—"),
                ])
            
            headers = [
                "Child Order ID",
                "Product",
                "Side",
                "Size",
                "Price",
                "Status",
                "Created At"
            ]
            
            # Add 2-space indent to all lines
            table_str = tabulate(
                child_rows,
                headers=headers,
                tablefmt="grid",
                disable_numparse=True
            )
            
            for line in table_str.split("\n"):
                print(f"  {line}")
    
    def display_summary_table(self, parents: List[Dict[str, Any]]) -> None:
        """Display all parent orders in a summary table.
        
        Args:
            parents: List of parent order dictionaries.
        """
        if not parents:
            print("[!] No parent orders found")
            return
        
        rows = []
        for parent in parents:
            parent_id = parent.get("client_order_id")
            children = self.get_children_for_parent(parent_id)
            
            rows.append([
                parent_id,
                parent.get("product_id", "—"),
                parent.get("side", "—"),
                self.format_numeric(parent.get("size")),
                self.format_numeric(parent.get("price")),
                self.format_numeric(parent.get("target_movement")),
                parent.get("status", "—").upper(),
                len(children),  # Number of child orders
                parent.get("created_at", "—"),
            ])
        
        headers = [
            "Parent Order ID",
            "Product",
            "Side",
            "Size",
            "Price",
            "Target %",
            "Status",
            "# Children",
            "Created At"
        ]
        
        print("\n" + "="*80)
        print(f"[P] PARENT ORDERS SUMMARY ({len(parents)} total)")
        print("="*80 + "\n")
        
        print(tabulate(rows, headers=headers, tablefmt="grid", disable_numparse=True))
        print()
    
    def run(
        self,
        parent_id: Optional[str] = None,
        status: Optional[str] = None,
        detail: bool = False
    ) -> None:
        """Run the CLI with the specified options.
        
        Args:
            parent_id: If provided, show only this parent order.
            status: If provided, filter parent orders by status.
            detail: Deprecated - detail view is now always shown by default.
        """
        try:
            # Fetch parent orders
            parents = self.get_parent_orders_data(parent_id=parent_id, status_filter=status)
            
            if not parents:
                if parent_id:
                    print(f"[!] No parent orders found matching: {parent_id}")
                elif status:
                    print(f"[!] No parent orders found with status: {status}")
                else:
                    print("[!] No parent orders found in database")
                return
            
            # Display results - always show detail view with children
            for parent in parents:
                self.display_parent_order(parent)
            print("\n")
        
        
        except Exception as e:
            print(f"[!] Error retrieving orders: {e}")
            raise


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Retrieve parent orders and their linked child orders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all parent orders with summary of child orders
  python %(prog)s

  # Show a specific parent order and all its child orders
  python %(prog)s --parent abc123def456

  # Filter parent orders by status
  python %(prog)s --status FILLED

  # Show detailed view with all children listed
  python %(prog)s --detail

  # Combine filters: show filled orders in detail
  python %(prog)s --status FILLED --detail
        """
    )
    
    parser.add_argument(
        "--parent",
        type=str,
        help="Show only this parent order ID (includes all child orders)"
    )
    
    parser.add_argument(
        "--status",
        type=str,
        help="Filter parent orders by status (e.g., OPEN, FILLED, CANCELLED)"
    )
    
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed view with child orders for each parent"
    )
    
    args = parser.parse_args()
    
    cli = ParentChildOrdersCLI()
    cli.run(
        parent_id=args.parent,
        status=args.status,
        detail=args.detail
    )


if __name__ == "__main__":
    main()
