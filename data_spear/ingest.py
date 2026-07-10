from __future__ import annotations

from collections.abc import Iterator

from data_spear.chunker import chunk_text, serialize_row
from data_spear.config import SOURCES, DocumentSource, RowSource, Source
from data_spear.db import stream_rows
from data_spear.vector_store import TEXT_FIELD, VectorStore


def _records_for_row_source(src: RowSource) -> Iterator[dict]:
    for row in stream_rows(src.table, src.columns, src.where):
        row_id = row.get(src.id_column)
        if row_id is None:
            continue
        yield {
            "_id": f"{src.table}:{row_id}",
            TEXT_FIELD: serialize_row(row),
            "source_table": src.table,
            "source_id": str(row_id),
            "kind": "row",
        }


def _records_for_document_source(src: DocumentSource) -> Iterator[dict]:
    cols = [src.id_column, *src.text_columns]
    for row in stream_rows(src.table, cols, src.where):
        row_id = row.get(src.id_column)
        if row_id is None:
            continue
        # Combine the chosen text columns into one document.
        parts = [str(row[c]) for c in src.text_columns if row.get(c)]
        if not parts:
            continue
        doc = "\n\n".join(parts)
        for i, chunk in enumerate(chunk_text(doc, src.chunk_size, src.chunk_overlap)):
            yield {
                "_id": f"{src.table}:{row_id}:{i}",
                TEXT_FIELD: chunk,
                "source_table": src.table,
                "source_id": str(row_id),
                "chunk_index": i,
                "kind": "document",
            }


def records_for(src: Source) -> Iterator[dict]:
    if isinstance(src, RowSource):
        return _records_for_row_source(src)
    if isinstance(src, DocumentSource):
        return _records_for_document_source(src)
    raise TypeError(f"unknown source: {type(src).__name__}")


def ingest_all(store: VectorStore | None = None) -> dict[str, int]:
    # Ingest every configured source into Pinecone. Returns counts per source.
    if not SOURCES:
        raise RuntimeError(
            "No sources configured. Edit SOURCES in config.py to point at your tables."
        )
    store = store or VectorStore()
    store.ensure_index()
    counts: dict[str, int] = {}
    for src in SOURCES:
        n = store.upsert(records_for(src))
        counts[f"{src.mode}:{src.table}"] = n
    return counts
