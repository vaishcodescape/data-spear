import hashlib
import logging
import mimetypes
import os
import re
from typing import Dict, List, Optional, Tuple

import psycopg2  # type: ignore[import-untyped]

from .embedder import generate_embedding

logger = logging.getLogger("omnigraph.ingestion")


def store_embedding(db: "DatabaseConnection", source_id: int, source_type: str, text: str) -> None:
    try:
        vector = generate_embedding(text)
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        with db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO omnigraph.embeddings
                    (source_id, source_type, vector, model_name, dimensions)
                VALUES (%s, %s, %s::vector, 'voyage-3', 1024)
                ON CONFLICT (source_type, source_id, model_name) DO UPDATE
                    SET vector     = EXCLUDED.vector,
                        updated_at = CURRENT_TIMESTAMP
                """,
                (source_id, source_type, vector_str),
            )
        db.conn.commit()
    except Exception as exc:
        logger.warning("Failed to store %s embedding for id=%d: %s", source_type, source_id, exc)
        try:
            db.conn.rollback()
        except Exception:
            pass


SUPPORTED_SOURCE_TYPES = {
    "report", "research_paper", "email", "technical_doc",
    "code_repository", "project_artifact", "presentation",
    "support_ticket", "log", "other",
}
SENSITIVITY_LEVELS = {"public", "internal", "confidential", "restricted"}
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200


# PostgreSQL connection using OMNIGRAPH_DB_USER/PASSWORD when set.
class DatabaseConnection:

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.connection_params = {
            "host": host or os.getenv("OMNIGRAPH_DB_HOST", "localhost"),
            "port": port or int(os.getenv("OMNIGRAPH_DB_PORT", "5432")),
            "dbname": dbname or os.getenv("OMNIGRAPH_DB_NAME", "omnigraph"),
            "user": user or os.getenv("OMNIGRAPH_DB_USER", "postgres"),
            "password": password or os.getenv("OMNIGRAPH_DB_PASSWORD", "postgres"),
        }
        self._conn = None

    def connect(self):
        try:
            self._conn = psycopg2.connect(**self.connection_params)
            self._conn.autocommit = False
            logger.info("Database connection established.")
        except psycopg2.Error as exc:
            logger.error("Failed to connect to database: %s", exc)
            raise

    def disconnect(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("Database connection closed.")

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self.connect()
        return self._conn


# Handles document ingest, deduplication, chunking, and versioning.
class DocumentIngester:

    def __init__(self, db: DatabaseConnection):
        self.db = db

    def ingest_document(
        self,
        title: str,
        source_type: str,
        content: str,
        uploaded_by: int,
        sensitivity_level: str = "internal",
        taxonomy_id: Optional[int] = None,
        file_path: Optional[str] = None,
        mime_type: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[int]:
        self._validate_source_type(source_type)
        self._validate_sensitivity(sensitivity_level)

        normalized = self.normalize_text(content)
        content_hash = self._compute_hash(normalized)

        existing_id = self._find_duplicate(content_hash)
        if existing_id is not None:
            logger.warning(
                "Duplicate detected for '%s' (matches document_id=%d). Creating new version.",
                title, existing_id,
            )
            self.create_version(existing_id, normalized, content_hash, uploaded_by)
            return existing_id

        file_size = len(normalized.encode("utf-8"))
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.documents
                        (title, source_type, content, summary, content_hash,
                         file_path, file_size_bytes, mime_type, sensitivity_level,
                         taxonomy_id, uploaded_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING document_id
                    """,
                    (
                        title, source_type, normalized, summary, content_hash,
                        file_path, file_size, mime_type, sensitivity_level,
                        taxonomy_id, uploaded_by,
                    ),
                )
                document_id = cur.fetchone()[0]
            self.db.conn.commit()
            logger.info("Ingested document '%s' (id=%d).", title, document_id)
            self._store_embedding(document_id, normalized)
            return document_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to ingest document '%s': %s", title, exc)
            return None

    def ingest_batch(self, documents: List[Dict]) -> Tuple[int, int]:
        success = failure = 0
        logger.info("Starting batch ingestion of %d documents.", len(documents))

        for idx, doc in enumerate(documents, start=1):
            try:
                result = self.ingest_document(
                    title=doc["title"],
                    source_type=doc["source_type"],
                    content=doc["content"],
                    uploaded_by=doc["uploaded_by"],
                    sensitivity_level=doc.get("sensitivity_level", "internal"),
                    taxonomy_id=doc.get("taxonomy_id"),
                    file_path=doc.get("file_path"),
                    mime_type=doc.get("mime_type"),
                    summary=doc.get("summary"),
                )
                if result is not None:
                    success += 1
                else:
                    failure += 1
            except Exception as exc:
                logger.error("Batch item %d failed: %s", idx, exc)
                failure += 1

        logger.info("Batch ingestion complete: %d succeeded, %d failed.", success, failure)
        return success, failure

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def chunk_document(
        content: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[Dict]:
        chunks = []
        start = index = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            chunks.append({
                "chunk_index": index,
                "start_pos": start,
                "end_pos": end,
                "text": content[start:end],
            })
            if end >= len(content):
                break
            start = end - overlap
            index += 1
        return chunks

    def create_version(
        self,
        document_id: int,
        new_content: str,
        content_hash: str,
        changed_by: int,
        change_summary: Optional[str] = None,
    ) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM omnigraph.document_versions WHERE document_id = %s
                    """,
                    (document_id,),
                )
                next_version = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO omnigraph.document_versions
                        (document_id, version_number, content, content_hash,
                         change_summary, changed_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING version_id
                    """,
                    (
                        document_id, next_version, new_content, content_hash,
                        change_summary or f"Version {next_version}", changed_by,
                    ),
                )
                version_id = cur.fetchone()[0]
            self.db.conn.commit()
            logger.info("Created version %d for document %d (version_id=%d).",
                        next_version, document_id, version_id)
            return version_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to create version for document %d: %s", document_id, exc)
            return None

    @staticmethod
    def extract_metadata(file_path: str) -> Dict:
        filename = os.path.basename(file_path)
        extension = os.path.splitext(filename)[1].lower()
        mime_guess, _ = mimetypes.guess_type(file_path)
        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        return {
            "filename": filename,
            "extension": extension,
            "size_bytes": size_bytes,
            "mime_type": mime_guess or "application/octet-stream",
        }

    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _find_duplicate(self, content_hash: str) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id FROM omnigraph.documents WHERE content_hash = %s LIMIT 1",
                    (content_hash,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except psycopg2.Error as exc:
            logger.error("Duplicate check failed: %s", exc)
            return None

    @staticmethod
    def _validate_source_type(source_type: str) -> None:
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type}'. Must be one of: {SUPPORTED_SOURCE_TYPES}"
            )

    @staticmethod
    def _validate_sensitivity(level: str) -> None:
        if level not in SENSITIVITY_LEVELS:
            raise ValueError(
                f"Invalid sensitivity_level '{level}'. Must be one of: {SENSITIVITY_LEVELS}"
            )

    def update_document(
        self,
        document_id: int,
        changed_by: int,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        sensitivity_level: Optional[str] = None,
        content: Optional[str] = None,
        change_summary: Optional[str] = None,
    ) -> Optional[int]:
        if all(v is None for v in (title, summary, sensitivity_level, content)):
            logger.warning("update_document: no fields to update for document_id=%s", document_id)
            return None
        if sensitivity_level is not None:
            self._validate_sensitivity(sensitivity_level)
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT title, summary, sensitivity_level, content, content_hash
                    FROM omnigraph.documents
                    WHERE document_id = %s AND is_archived = FALSE
                    """,
                    (document_id,),
                )
                row = cur.fetchone()
                if not row:
                    logger.warning("update_document: document %s not found or archived.", document_id)
                    return None
                cur_title, cur_summary, cur_sens, cur_content, cur_hash = row

                new_title = title if title is not None else cur_title
                new_summary = summary if summary is not None else cur_summary
                new_sens = sensitivity_level if sensitivity_level is not None else cur_sens
                new_content = cur_content
                new_hash = cur_hash

                if content is not None:
                    normalized = self.normalize_text(content)
                    new_content = normalized
                    new_hash = self._compute_hash(normalized)
                    if new_hash != cur_hash:
                        cur.execute(
                            """
                            SELECT COALESCE(MAX(version_number), 0) + 1
                            FROM omnigraph.document_versions WHERE document_id = %s
                            """,
                            (document_id,),
                        )
                        next_version = cur.fetchone()[0]
                        cur.execute(
                            """
                            INSERT INTO omnigraph.document_versions
                                (document_id, version_number, content, content_hash,
                                 change_summary, changed_by)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                document_id,
                                next_version,
                                new_content,
                                new_hash,
                                change_summary or f"Agent update v{next_version}",
                                changed_by,
                            ),
                        )

                cur.execute(
                    """
                    UPDATE omnigraph.documents
                    SET title = %s, summary = %s, sensitivity_level = %s,
                        content = %s, content_hash = %s,
                        file_size_bytes = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = %s
                    """,
                    (
                        new_title,
                        new_summary,
                        new_sens,
                        new_content,
                        new_hash,
                        len(new_content.encode("utf-8")),
                        document_id,
                    ),
                )
            self.db.conn.commit()
            logger.info("Updated document id=%s.", document_id)
            if content is not None and new_hash != cur_hash:
                self._store_embedding(document_id, new_content)
            return document_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to update document %s: %s", document_id, exc)
            return None

    def _store_embedding(self, document_id: int, text: str) -> None:
        store_embedding(self.db, document_id, "document", text)

    def reembed_all_documents(self) -> Tuple[int, int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute("DELETE FROM omnigraph.embeddings WHERE source_type = 'document'")
                deleted = cur.rowcount
            self.db.conn.commit()
            logger.info("Cleared %d existing document embeddings.", deleted)
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to clear embeddings table: %s", exc)
            return 0, 0

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id, content FROM omnigraph.documents WHERE is_archived = FALSE"
                )
                rows = cur.fetchall()
        except psycopg2.Error as exc:
            logger.error("Failed to fetch documents for re-embedding: %s", exc)
            return 0, 0

        logger.info("Re-embedding %d documents with Voyage AI…", len(rows))
        success = failure = 0
        for document_id, content in rows:
            try:
                self._store_embedding(document_id, content)
                success += 1
            except Exception as exc:
                logger.error("Failed to re-embed document %d: %s", document_id, exc)
                failure += 1

        logger.info("Re-embedding complete: %d succeeded, %d failed.", success, failure)
        return success, failure

    def set_document_archived(self, document_id: int, archived: bool) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE omnigraph.documents
                    SET is_archived = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = %s
                    """,
                    (archived, document_id),
                )
                ok = cur.rowcount > 0
            self.db.conn.commit()
            return ok
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("set_document_archived failed for %s: %s", document_id, exc)
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db = DatabaseConnection()
    db.connect()
    ingester = DocumentIngester(db)

    doc_id = ingester.ingest_document(
        title="Test Document - Ingestion Pipeline Validation",
        source_type="technical_doc",
        content=(
            "This is a test document created by the ingestion pipeline. "
            "It validates that the pipeline correctly normalizes text, "
            "computes content hashes, and stores documents in PostgreSQL."
        ),
        uploaded_by=1,
        sensitivity_level="internal",
        summary="Pipeline validation test document.",
    )

    if doc_id:
        print(f"SUCCESS: Document ingested with id={doc_id}")
        chunks = ingester.chunk_document("A" * 5000, chunk_size=2000, overlap=200)
        print(f"Document chunked into {len(chunks)} segments.")
    else:
        print("FAILED: Document ingestion returned None.")

    db.disconnect()
