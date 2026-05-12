"""FastAPI dependency injection for database connections (pool-backed)."""
from typing import Generator

from omnigraph.database import get_connection
from omnigraph.ingestion_pipeline import DatabaseConnection


def get_db() -> Generator[DatabaseConnection, None, None]:
    """Yield a DatabaseConnection backed by the shared connection pool.

    The raw connection is returned to the pool automatically when the
    request completes (or errors), so callers must not call disconnect().
    """
    with get_connection() as raw_conn:
        yield DatabaseConnection(conn=raw_conn)
