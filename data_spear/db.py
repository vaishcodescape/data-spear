from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import uuid4

import psycopg2
import psycopg2.extras
from psycopg2 import sql as pgsql

from config import settings


# DSN chosen at runtime (e.g. credentials the user entered via the CLI). When unset,
# we fall back to the static value from .env / config.
_active_dsn: str | None = None


def set_active_dsn(dsn: str) -> None:
   # Override the DSN used for every subsequent connection.
    global _active_dsn
    _active_dsn = dsn


def active_dsn() -> str:
    return _active_dsn or settings.pg_dsn


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    conn = psycopg2.connect(active_dsn())
    try:
        yield conn
    finally:
        conn.close()


def stream_rows(
    table: str,
    columns: list[str] | None,
    where: str | None,
    batch_size: int = 500,
) -> Iterator[dict]:
    # Yield rows from `table` as dicts. Streams via a server-side cursor.
    col_sql = (
        pgsql.SQL(", ").join(pgsql.Identifier(c) for c in columns)
        if columns
        else pgsql.SQL("*")
    )
    # `table` may be schema-qualified; Identifier(*parts) quotes each part.
    query = pgsql.SQL("SELECT {cols} FROM {table}").format(
        cols=col_sql, table=pgsql.Identifier(*table.split("."))
    )
    if where:
        # `where` comes from trusted config (SOURCES), not user input.
        query = pgsql.SQL("{q} WHERE {w}").format(q=query, w=pgsql.SQL(where))

    with connect() as conn:
        with conn.cursor(
            name=f"data_spear_{uuid4().hex}",  # named cursor = server-side
            cursor_factory=psycopg2.extras.RealDictCursor,
        ) as cur:
            cur.itersize = batch_size
            cur.execute(query)
            for row in cur:
                yield dict(row)
