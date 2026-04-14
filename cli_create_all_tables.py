""" Create database tables """

from database.order import create_order_parent_table, create_order_child_table

def main():
    """ Main function to create tables """
    create_order_parent_table()
    create_order_child_table()
    print("All tables created successfully!")

if __name__ == "__main__":
    main()
