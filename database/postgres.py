import psycopg2
from psycopg2 import sql

CREATE_TABLES_QUERIES = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        uuid UUID UNIQUE NOT NULL,
        name VARCHAR(255) NOT NULL,
        currency VARCHAR(50) NOT NULL,
        available_balance_value NUMERIC(30, 18) NOT NULL,
        available_balance_currency VARCHAR(50),
        default_account BOOLEAN DEFAULT false,
        active BOOLEAN DEFAULT true,
        created_at TIMESTAMP WITH TIME ZONE,
        updated_at TIMESTAMP WITH TIME ZONE,
        deleted_at TIMESTAMP WITH TIME ZONE,
        type VARCHAR(100),
        ready BOOLEAN DEFAULT false,
        hold_value NUMERIC(30, 18),
        hold_currency VARCHAR(50),
        retail_portfolio_id UUID,
        platform VARCHAR(100),
        created_at_db TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        id SERIAL PRIMARY KEY,
        profile_id VARCHAR(255) UNIQUE,
        user_id VARCHAR(255),
        name VARCHAR(255),
        created_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        product_id VARCHAR(50) UNIQUE,
        base_currency VARCHAR(10),
        quote_currency VARCHAR(10),
        display_name VARCHAR(100),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_tickers (
        id SERIAL PRIMARY KEY,
        product_id VARCHAR(50),
        price DECIMAL(20, 8),
        size DECIMAL(20, 8),
        time TIMESTAMP,
        trade_id BIGINT,
        side VARCHAR(10),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )
    """
]

class CoinbaseDatabase:
    def __init__(self, host, database, user, password, port=5432):
        self.conn = psycopg2.connect(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port
        )
        self.cursor = self.conn.cursor()

    def create_tables(self):
        """Create tables for Coinbase data"""
        
        # Profile/Account table

        for query in CREATE_TABLES_QUERIES:
            self.cursor.execute(query)
            self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()


if __name__ == "__main__":
    db = CoinbaseDatabase(
        host="localhost",
        port=3306,
        database="postgres",
        user="postgres",
        password="postgres"
    )
    db.create_tables()
    print("Tables created successfully")
    db.close()