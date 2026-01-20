import os
from contextlib import contextmanager
from typing import Iterator, Optional
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Global connection pool (initialized at app startup)
_pool: Optional[ConnectionPool] = None

def get_database_url() -> str:
   url = os.getenv("DATABASE_URL")
   if not url:
       raise RuntimeError("DATABASE_URL is not set (Codespaces secret).")
   return url

def init_pool(min_size: int = 2, max_size: int = 10) -> None:
    """
    Initialize connection pool. Call once at app startup.

    Args:
        min_size: Minimum number of connections to maintain
        max_size: Maximum number of connections allowed
    """
    global _pool
    if _pool is not None:
        raise RuntimeError("Connection pool already initialized")

    _pool = ConnectionPool(
        conninfo=get_database_url(),
        min_size=min_size,
        max_size=max_size,
        kwargs={'row_factory': dict_row}
    )

def get_pool() -> ConnectionPool:
    """Get the connection pool."""
    if _pool is None:
        raise RuntimeError("Pool not initialized. Call init_pool() first.")
    return _pool

@contextmanager
def get_conn() -> Iterator[Connection]:
    """
    Get a database connection from the pool.

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
    """
    if _pool is None:
        # Fallback for backward compatibility (tests, scripts)
        conn: Connection = Connection.connect(get_database_url(), row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()
    else:
        # Use pool
        with _pool.connection() as conn:
            yield conn

def close_pool() -> None:
    """Close the connection pool. Call at app shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

def init_db(schema_path: str) -> None:
   with open(schema_path, "r", encoding="utf-8") as f:
       ddl = f.read()
   with get_conn() as conn:
       with conn.cursor() as cur:
           cur.execute(ddl)
       conn.commit()