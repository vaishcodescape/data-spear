from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extensions
from psycopg2 import pool as pg_pool

from .config import settings

logger = logging.getLogger("omnigraph.database")

_pool: pg_pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    _pool = pg_pool.ThreadedConnectionPool(
        minconn=settings.db_pool_min,
        maxconn=settings.db_pool_max,
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    logger.info(
        "Connection pool initialized (min=%d, max=%d, host=%s/%s).",
        settings.db_pool_min,
        settings.db_pool_max,
        settings.db_host,
        settings.db_name,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Connection pool closed.")


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    if _pool is None:
        raise RuntimeError(
            "Connection pool is not initialized. Call init_pool() first."
        )
    conn = _pool.getconn()
    conn.autocommit = False
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
