"""FastAPI dependency injection for database connections."""
from typing import Generator

from omnigraph.ingestion_pipeline import DatabaseConnection


def get_db() -> Generator[DatabaseConnection, None, None]:
    """
    Yield a fresh DatabaseConnection per request and close it when done.
    All connection parameters are read from environment variables
    (OMNIGRAPH_DB_HOST, OMNIGRAPH_DB_PORT, OMNIGRAPH_DB_NAME, etc.).
    """
    db = DatabaseConnection()
    db.connect()
    try:
        yield db
    finally:
        db.disconnect()
