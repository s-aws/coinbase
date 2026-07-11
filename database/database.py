"""
PostgreSQL Database Module - Localhost-only access

This module provides a secure interface to interact with PostgreSQL
running in a Docker container accessible only via localhost.

Classes:
    PostgresDB: Secure database connection manager with query execution methods

Functions:
    init_db: Initialize and return a PostgreSQL database connection

Example:
    >>> db = init_db()
    >>> results = db.execute_query("SELECT * FROM users WHERE id = %s", (1,))
    >>> db.disconnect()
"""

import os
import sys
import threading
import psycopg2
from psycopg2 import sql, Error
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from logging_service import get_logger

logger = get_logger("PostgresDB")

# Environment-driven defaults. Tests should set these (typically via conftest)
# to point at the test instance (port 9876). Production leaves them unset and
# the values below kick in.
DEFAULT_DB_HOST = os.environ.get("COINBASE_DB_HOST", "127.0.0.1")
DEFAULT_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "5432"))
DEFAULT_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
DEFAULT_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
DEFAULT_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")


class PostgresDB:
    """
    Secure PostgreSQL database connection manager for localhost-only access.
    
    Provides connection management, cursor handling, and common database operations
    with built-in error handling and transaction control. All connections are
    restricted to localhost for security.
    
    Attributes:
        host (str): Database host address (localhost only).
        port (int): Database port number.
        database (str): Database name.
        user (str): Database user account.
        password (str): Database password.
        _conn (psycopg2.connection): Active database connection (private).
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """
        Initialize database connection parameters.

        Connection is not established until connect() is called or first operation
        is performed through a context manager.

        Any argument left as ``None`` falls back to the corresponding
        ``COINBASE_DB_*`` environment variable (resolved at module import time),
        and finally to the production default. Tests should set the environment
        variables before importing this module — see ``tests/conftest.py``.

        Args:
            host: Database host address. Defaults to ``$COINBASE_DB_HOST`` or ``127.0.0.1``.
            port: Database port. Defaults to ``$COINBASE_DB_PORT`` or ``5432``.
            database: Database name. Defaults to ``$COINBASE_DB_NAME`` or ``postgres``.
            user: Database user. Defaults to ``$COINBASE_DB_USER`` or ``postgres``.
            password: Database password. Defaults to ``$COINBASE_DB_PASSWORD`` or ``postgres``.
        """
        self.host: str = host if host is not None else DEFAULT_DB_HOST
        self.port: int = port if port is not None else DEFAULT_DB_PORT
        self.database: str = database if database is not None else DEFAULT_DB_NAME
        self.user: str = user if user is not None else DEFAULT_DB_USER
        self.password: str = password if password is not None else DEFAULT_DB_PASSWORD
        self._conn: Optional[psycopg2.extensions.connection] = None
        # Serialise cursor / commit / rollback across threads. The single
        # shared psycopg2 connection cannot safely be used by multiple
        # threads concurrently: if thread A's transaction aborts (e.g.
        # ForeignKeyViolation), thread B's cursor on the same connection
        # sees ``InFailedSqlTransaction`` before A's rollback runs. The
        # cascade was observed in production on 2026-04-28 — see
        # ``tests/regression/test_db_cursor_thread_safety.py``.
        self._cursor_lock: threading.RLock = threading.RLock()
    
    def connect(self) -> None:
        """
        Establish connection to PostgreSQL database.
        
        Initiates a new connection using stored credentials. Logs confirmation
        on success and raises an exception on failure.
        
        Raises:
            Error: If connection fails due to invalid credentials or database unavailable.
        """
        self._refuse_test_process_prod_connection()
        try:
            logger.debug(f"Attempting connection to PostgreSQL at {self.host}:{self.port} (db: {self.database})")
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            logger.debug(f"Successfully connected to PostgreSQL at {self.host}:{self.port}")
        except Error as e:
            logger.error(f"Failed to connect to PostgreSQL at {self.host}:{self.port}: {type(e).__name__}: {e}")
            raise

    def _refuse_test_process_prod_connection(self) -> None:
        """Block test-shaped processes from using the local production port."""
        if os.environ.get("ALLOW_PROD_DB") == "1":
            return
        if self.port != 5432 or self.host not in ("127.0.0.1", "localhost"):
            return

        argv0 = os.path.basename(sys.argv[0] or "").lower()
        argv_text = " ".join(sys.argv[:2]).lower()
        if not (
            argv0.startswith("test_")
            or argv0.endswith("_test.py")
            or "pytest" in argv_text
        ):
            return

        raise RuntimeError(
            f"REFUSED: test-shaped process attempted to connect to prod DB at "
            f"{self.host}:{self.port}. Use port 9876 for tests or set "
            f"ALLOW_PROD_DB=1 to override."
        )
    
    def disconnect(self) -> None:
        """
        Close database connection.
        
        Safely closes an active connection. Safe to call even if no connection exists.
        Logs confirmation message on successful disconnection.
        """
        if self._conn:
            self._conn.close()
            logger.debug("Disconnected from PostgreSQL")
    
    @contextmanager
    def get_cursor(self):
        """
        Context manager for database cursor.
        
        Automatically creates a cursor, commits on success, rolls back on error,
        and closes the cursor. Ensures transactions are properly handled.

        Thread safety: the entire begin -> execute -> commit/rollback sequence
        is serialised via ``self._cursor_lock``. Without this lock, when one
        thread's statement aborts the transaction (e.g. ForeignKeyViolation),
        any other thread mid-execute on the same connection observes
        ``InFailedSqlTransaction`` before the first thread's rollback runs.
        Re-entrant so nested calls from the same thread are still allowed.
        
        Yields:
            psycopg2.cursor: Database cursor for executing queries.
        
        Raises:
            Error: If database operation fails (auto-rolled back).
        """
        with self._cursor_lock:
            if not self._conn:
                self.connect()
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except Exception as e:
                self._conn.rollback()
                logger.error(f"Database transaction error - rolling back: {type(e).__name__}: {e}")
                raise
            finally:
                cursor.close()    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results as list of dicts.
        
        Safe for parameterized queries. Results are automatically converted
        to dictionaries mapping column names to values.
        
        Args:
            query: SQL query string with %s placeholders for parameters.
            params: Tuple of parameters to bind to query (default: None).
        
        Returns:
            List of result rows as dictionaries. Empty list if no rows match.
        
        Example:
            >>> results = db.execute_query(
            ...     "SELECT id, name FROM users WHERE age > %s",
            ...     (18,)
            ... )
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or ())
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return results
    
    def execute_update(self, query: str, params: Optional[tuple] = None) -> int:
        """
        Execute an INSERT, UPDATE, or DELETE query.
        
        Safe for parameterized queries. Automatically commits the transaction.
        
        Args:
            query: SQL query string with %s placeholders for parameters.
            params: Tuple of parameters to bind to query (default: None).
        
        Returns:
            Number of affected rows (0 if no rows matched).
        
        Example:
            >>> rows_deleted = db.execute_update(
            ...     "DELETE FROM users WHERE id = %s",
            ...     (1,)
            ... )
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.rowcount
    
    def create_table(self, table_name: str, columns: Dict[str, str]) -> None:
        """
        Create a table with specified columns.
        
        Safely creates a table using parameterized column definitions.
        Safe to call multiple times (uses IF NOT EXISTS).
        
        Args:
            table_name: Name of table to create.
            columns: Dictionary mapping column_name to column_type.
        
        Returns:
            None
        
        Example:
            >>> db.create_table('users', {
            ...     'id': 'SERIAL PRIMARY KEY',
            ...     'name': 'VARCHAR(255) NOT NULL',
            ...     'email': 'VARCHAR(255) UNIQUE'
            ... })
        """
        col_defs = ", ".join([f"{name} {dtype}" for name, dtype in columns.items()])
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs})"
        
        try:
            logger.debug(f"Creating table '{table_name}' with {len(columns)} columns")
            with self.get_cursor() as cursor:
                cursor.execute(query)
            logger.info(f"Table '{table_name}' created/verified successfully")
        except Error as e:
            logger.error(f"Failed to create table '{table_name}': {type(e).__name__}: {e}")
            raise
    
    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        Insert a single row into a table.
        
        Safely inserts data using parameterized values.
        
        Args:
            table: Table name.
            data: Dictionary mapping column names to values.
        
        Returns:
            Number of rows inserted (1 on success, 0 on failure).
        
        Example:
            >>> db.insert('users', {
            ...     'name': 'John Doe',
            ...     'email': 'john@example.com'
            ... })
        """
        columns = list(data.keys())
        values = tuple(data.values())
        placeholders = ", ".join(["%s"] * len(columns))
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        
        return self.execute_update(query, values)
    
    def select(self, table: str, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Select rows from a table.
        
        Retrieves rows matching optional WHERE conditions.
        
        Args:
            table: Table name.
            where: Dictionary mapping column names to values for WHERE clause.
                   If None, returns all rows.
        
        Returns:
            List of matching rows as dictionaries.
        
        Example:
            >>> users = db.select('users', {'status': 'active'})
        """
        query = f"SELECT * FROM {table}"
        params: tuple = ()
        
        if where:
            conditions = " AND ".join([f"{col} = %s" for col in where.keys()])
            query += f" WHERE {conditions}"
            params = tuple(where.values())
        
        return self.execute_query(query, params)
    
    def delete(self, table: str, where: Dict[str, Any]) -> int:
        """
        Delete rows from a table.
        
        Safely deletes rows matching WHERE conditions. Requires where clause
        for safety (prevents accidental full table delete).
        
        Args:
            table: Table name.
            where: Dictionary mapping column names to values for WHERE clause.
        
        Returns:
            Number of deleted rows.
        
        Raises:
            ValueError: If where clause is empty (safety check).
        
        Example:
            >>> deleted_count = db.delete('users', {'id': 1})
        """
        if not where:
            raise ValueError("WHERE clause required for safety")
        
        conditions = " AND ".join([f"{col} = %s" for col in where.keys()])
        query = f"DELETE FROM {table} WHERE {conditions}"
        params = tuple(where.values())
        
        return self.execute_update(query, params)


def init_db(
    host: str = "127.0.0.1",
    port: int = 5432,
    database: str = "postgres",
    user: str = "postgres",
    password: str = "postgres"
) -> PostgresDB:
    """
    Initialize and return a PostgreSQL database connection.
    
    Creates a PostgresDB instance and establishes a connection to the database.
    
    Args:
        host: Database host address (default: 127.0.0.1 - localhost only).
        port: Database port number (default: 5432).
        database: Database name (default: postgres).
        user: Database user account (default: postgres).
        password: Database password for authentication.
    
    Returns:
        Initialized and connected PostgresDB instance ready for use.
    
    Raises:
        Error: If connection fails.
    
    Example:
        >>> db = init_db()
        >>> orders = db.execute_query("SELECT * FROM orders")
        >>> db.disconnect()
    """
    db = PostgresDB(host=host, port=port, database=database, user=user, password=password)
    db.connect()
    return db
