""" Create database tables """

from database.order import create_order_parent_table, create_order_child_table

def main() -> None:
    """
    Create all required database tables for order tracking.
    
    Initializes parent and child order tables in the database.
    
    Returns:
        None
    """
    create_order_parent_table()
    create_order_child_table()
    print("All tables created successfully!")

if __name__ == "__main__":
    main()
