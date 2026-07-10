import pytest

import data_spear.ingest as ingest
from data_spear.config import DocumentSource, RowSource


def test_row_source_records(monkeypatch):
    rows = [
        {"id": 1, "name": "Ada", "email": None},
        {"id": None, "name": "ghost"},  # no id -> skipped
        {"id": 2, "name": "Bob"},
    ]
    monkeypatch.setattr(ingest, "stream_rows", lambda *a, **k: iter(rows))
    src = RowSource(table="customers")
    records = list(ingest.records_for(src))
    assert [r["_id"] for r in records] == ["customers:1", "customers:2"]
    assert records[0]["chunk_text"] == "id: 1\nname: Ada"
    assert records[0]["kind"] == "row"
    assert records[0]["source_id"] == "1"


def test_document_source_records(monkeypatch):
    body = " ".join(f"w{i}" for i in range(300))
    rows = [
        {"id": 10, "title": "T", "body": body},
        {"id": 11, "title": None, "body": None},  # no text -> skipped
    ]
    monkeypatch.setattr(ingest, "stream_rows", lambda *a, **k: iter(rows))
    src = DocumentSource(
        table="articles", text_columns=["title", "body"], chunk_size=200, chunk_overlap=20
    )
    records = list(ingest.records_for(src))
    assert records, "expected chunks from the long document"
    assert all(r["_id"].startswith("articles:10:") for r in records)
    assert [r["chunk_index"] for r in records] == list(range(len(records)))
    assert all(r["kind"] == "document" for r in records)


def test_records_for_unknown_source_type():
    with pytest.raises(TypeError):
        ingest.records_for(object())


def test_ingest_all_requires_sources(monkeypatch):
    monkeypatch.setattr(ingest, "SOURCES", [])
    with pytest.raises(RuntimeError, match="No sources configured"):
        ingest.ingest_all(store=object())
