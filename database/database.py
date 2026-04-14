"""
PostgreSQL Database Module - Localhost-only access
This module provides a secure interface to interact with PostgreSQL
running in a Docker container accessible only via localhost.
"""

import psycopg2
from psycopg2 import sql, Error
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


class PostgresDB:
    """Secure PostgreSQL database connection manager for localhost-only access."""
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5432,
        database: str = "postgres",
        user: str = "postgres",
        password: str = "postgres"
    ):
        """
        Initialize database connection parameters.
        
        Args:
            host: Database host (default: 127.0.0.1 - localhost only)
            port: Database port (default: 5432)
            database: Database name (default: postgres)
            user: Database user (default: postgres)
            password: Database password
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._conn = None
    
    def connect(self) -> None:
        """Establish connection to PostgreSQL database."""
        try:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            print(f"Connected to PostgreSQL at {self.host}:{self.port}")
        except Error as e:
            print(f"Error connecting to PostgreSQL: {e}")
            raise
    
    def disconnect(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            print("Disconnected from PostgreSQL")
    
    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor."""
        if not self._conn:
            self.connect()
        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Error as e:
            self._conn.rollback()
            print(f"Database error: {e}")
            raise
        finally:
            cursor.close()
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results as list of dicts.
        
        Args:
            query: SQL query string
            params: Query parameters for safe execution
        
        Returns:
            List of result rows as dictionaries
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or ())
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return results
    
    def execute_update(self, query: str, params: tuple = None) -> int:
        """
        Execute an INSERT, UPDATE, or DELETE query.
        
        Args:
            query: SQL query string
            params: Query parameters for safe execution
        
        Returns:
            Number of affected rows
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.rowcount
    
    def create_table(self, table_name: str, columns: Dict[str, str]) -> None:
        """
        Create a table with specified columns.
        
        Args:
            table_name: Name of table to create
            columns: Dictionary of column_name: column_type pairs
        
        Example:
            db.create_table('users', {
                'id': 'SERIAL PRIMARY KEY',
                'name': 'VARCHAR(255) NOT NULL',
                'email': 'VARCHAR(255) UNIQUE'
            })
        """
        col_defs = ", ".join([f"{name} {dtype}" for name, dtype in columns.items()])
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs})"
        
        with self.get_cursor() as cursor:
            cursor.execute(query)
        print(f"Table '{table_name}' created successfully")
    
    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        Insert a single row into a table.
        
        Args:
            table: Table name
            data: Dictionary of column: value pairs
        
        Returns:
            Number of rows inserted (1 on success)
        """
        columns = list(data.keys())
        values = tuple(data.values())
        placeholders = ", ".join(["%s"] * len(columns))
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        
        return self.execute_update(query, values)
    
    def select(self, table: str, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Select rows from a table.
        
        Args:
            table: Table name
            where: Dictionary of column: value pairs for WHERE clause
        
        Returns:
            List of matching rows as dictionaries
        """
        query = f"SELECT * FROM {table}"
        params = ()
        
        if where:
            conditions = " AND ".join([f"{col} = %s" for col in where.keys()])
            query += f" WHERE {conditions}"
            params = tuple(where.values())
        
        return self.execute_query(query, params)
    
    def delete(self, table: str, where: Dict[str, Any]) -> int:
        """
        Delete rows from a table.
        
        Args:
            table: Table name
            where: Dictionary of column: value pairs for WHERE clause
        
        Returns:
            Number of deleted rows
        """
        if not where:
            raise ValueError("WHERE clause required for safety")
        
        conditions = " AND ".join([f"{col} = %s" for col in where.keys()])
        query = f"DELETE FROM {table} WHERE {conditions}"
        params = tuple(where.values())
        
        return self.execute_update(query, params)


# Initialize database module for easy import
def init_db(
    host: str = "127.0.0.1",
    port: int = 5432,
    database: str = "postgres",
    user: str = "postgres",
    password: str = "postgres"
) -> PostgresDB:
    """
    Initialize and return a PostgreSQL database connection.
    
    Args:
        host: Database host (localhost only by default)
        port: Database port
        database: Database name
        user: Database user
        password: Database password
    
    Returns:
        PostgresDB instance ready for use
    """
    db = PostgresDB(host=host, port=port, database=database, user=user, password=password)
    db.connect()
    return db
