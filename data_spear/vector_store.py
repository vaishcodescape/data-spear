from __future__ import annotations

import time
from typing import Iterable

from pinecone import Pinecone
from pinecone.exceptions import NotFoundException

from config import settings


# Field map convention: every record stores its text in `chunk_text`.
# Pinecone's integrated inference embeds this field server-side.
TEXT_FIELD = "chunk_text"


# Namespace chosen at runtime — derived from the connected database identity so
# that chunks ingested from one database are never retrieved as context for
# another. Falls back to the static config value when /connect was never called.
_active_namespace: str | None = None


def set_active_namespace(namespace: str) -> None:
    global _active_namespace
    _active_namespace = namespace


def active_namespace() -> str:
    return _active_namespace or settings.pinecone_namespace


class VectorStore:
    def __init__(self) -> None:
        if not settings.pinecone_api_key:
            raise RuntimeError("PINECONE_API_KEY is not set")
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index = None

    #index lifecycle 

    def ensure_index(self) -> None:
        # Create the index with integrated embedding if it doesn't exist
        existing = {i["name"] for i in self._pc.list_indexes()}
        if settings.pinecone_index not in existing:
            self._pc.create_index_for_model(
                name=settings.pinecone_index,
                cloud=settings.pinecone_cloud,
                region=settings.pinecone_region,
                embed={
                    "model": settings.embedding_model,
                    "field_map": {"text": TEXT_FIELD},
                },
            )
            # Wait for it to become ready.
            for _ in range(60):
                desc = self._pc.describe_index(settings.pinecone_index)
                if desc.status.get("ready"):
                    break
                time.sleep(1)

    def _idx(self):
        if self._index is None:
            self._index = self._pc.Index(settings.pinecone_index)
        return self._index


    def upsert(self, records: Iterable[dict], batch_size: int = 96) -> int:
        # Upsert records. Each record must contain `_id` and `chunk_text` plus optional metadata.
        batch: list[dict] = []
        total = 0
        idx = self._idx()
        for rec in records:
            batch.append(rec)
            if len(batch) >= batch_size:
                idx.upsert_records(namespace=active_namespace(), records=batch)
                total += len(batch)
                batch = []
        if batch:
            idx.upsert_records(namespace=active_namespace(), records=batch)
            total += len(batch)
        return total


    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        # Semantic search via integrated inference. Returns list of hit dicts with id/score/fields.
        try:
            result = self._idx().search(
                namespace=active_namespace(),
                query={"inputs": {"text": query}, "top_k": top_k or settings.top_k},
            )
        except NotFoundException:
            return []
        hits = result.get("result", {}).get("hits", []) if isinstance(result, dict) else result.result.hits
        out: list[dict] = []
        for hit in hits:
            # SDK returns objects in newer versions; normalize to dicts.
            if hasattr(hit, "_id"):
                out.append({
                    "id": getattr(hit, "_id", None),
                    "score": getattr(hit, "_score", None),
                    "fields": dict(getattr(hit, "fields", {}) or {}),
                })
            else:
                out.append({
                    "id": hit.get("_id"),
                    "score": hit.get("_score"),
                    "fields": dict(hit.get("fields", {}) or {}),
                })
        return out
