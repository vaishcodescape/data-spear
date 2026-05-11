"""
OmniGraph REST API
==================
FastAPI application exposing the full OmniGraph pipeline over HTTP.

Endpoints
---------
GET  /health
POST /api/v1/auth/login
POST /api/v1/documents/ingest
POST /api/v1/documents/upload
POST /api/v1/documents/ingest-url
GET  /api/v1/documents
GET  /api/v1/documents/{doc_id}
DELETE /api/v1/documents/{doc_id}
POST /api/v1/search
POST /api/v1/chat
GET  /api/v1/graph/stats
GET  /api/v1/graph/entities
GET  /api/v1/graph/entities/{entity_id}/neighborhood
POST /api/v1/graph/build

Run locally:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from omnigraph.access_control_audit import AccessControlManager
from omnigraph.agentic_rag import AnthropicOmniGraphAgent
from omnigraph.entity_relation_extractor import EntityRelationExtractor
from omnigraph.graph_builder import KnowledgeGraphBuilder
from omnigraph.ingestion_pipeline import DatabaseConnection, DocumentIngester
from omnigraph.semantic_query_engine import SemanticQueryEngine

from .auth import require_api_key
from .dependencies import get_db
from .file_parser import parse_file, parse_url
from .models import (
    BuildGraphResponse,
    ChatRequest,
    ChatResponse,
    DocumentDetail,
    DocumentSummary,
    EntityItem,
    GraphStatsResponse,
    IngestResponse,
    IngestTextRequest,
    IngestUrlRequest,
    LoginRequest,
    LoginResponse,
    NeighborhoodResponse,
    SearchRequest,
    SearchResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("omnigraph.api")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OmniGraph API",
    description=(
        "Enterprise Knowledge Graph & Agentic RAG — fully automated REST interface.\n\n"
        "All `/api/v1/*` endpoints require an `X-API-Key` header "
        "(set `OMNIGRAPH_API_KEY` env var; leave empty to disable auth in dev)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health(db: DatabaseConnection = Depends(get_db)) -> Dict[str, Any]:
    """Ping the database and return service status."""
    try:
        with db.conn.cursor() as cur:
            cur.execute("SELECT 1")
        db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "llm_extraction": bool(os.getenv("ANTHROPIC_API_KEY")),
        "semantic_search": bool(os.getenv("VOYAGE_API_KEY")),
    }


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/v1/auth/login", tags=["Auth"])
def login(body: LoginRequest, db: DatabaseConnection = Depends(get_db)) -> LoginResponse:
    """
    Look up a user by username and return their user_id + assigned roles.
    Use the returned ``user_id`` in subsequent search / chat requests.
    """
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id, u.username, u.full_name
                FROM omnigraph.users u
                WHERE u.username = %s AND u.is_active = TRUE
                """,
                (body.username,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User '{body.username}' not found or inactive.",
                )
            user_id, username, full_name = row

            cur.execute(
                """
                SELECT r.name FROM omnigraph.roles r
                JOIN omnigraph.user_roles ur ON ur.role_id = r.role_id
                WHERE ur.user_id = %s
                """,
                (user_id,),
            )
            roles = [r[0] for r in cur.fetchall()]
    except psycopg2.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return LoginResponse(
        user_id=user_id,
        username=username,
        full_name=full_name,
        roles=roles,
    )


# ── Documents — text ingest ───────────────────────────────────────────────────

@app.post(
    "/api/v1/documents/ingest",
    tags=["Documents"],
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
)
def ingest_text(
    body: IngestTextRequest,
    db: DatabaseConnection = Depends(get_db),
) -> IngestResponse:
    """Ingest a plain-text document into the knowledge graph."""
    ingester = DocumentIngester(db)
    doc_id = ingester.ingest_document(
        title=body.title,
        source_type=body.source_type,
        content=body.content,
        uploaded_by=body.uploaded_by,
        sensitivity_level=body.sensitivity_level,
        summary=body.summary,
    )
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document ingestion failed.")

    extraction = None
    if body.auto_extract:
        extractor = EntityRelationExtractor(db)
        extraction = extractor.process_document(doc_id)
        extraction = {
            "entities": len(extraction["entities"]),
            "concepts": len(extraction["concepts"]),
            "relationships": len(extraction["relationships"]),
        }

    return IngestResponse(document_id=doc_id, status="ingested", extraction=extraction)


# ── Documents — file upload ───────────────────────────────────────────────────

@app.post(
    "/api/v1/documents/upload",
    tags=["Documents"],
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
)
async def upload_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    source_type: str = Form(default="other"),
    uploaded_by: int = Form(...),
    sensitivity_level: str = Form(default="internal"),
    summary: Optional[str] = Form(default=None),
    auto_extract: bool = Form(default=True),
    db: DatabaseConnection = Depends(get_db),
) -> IngestResponse:
    """
    Upload a file (PDF, DOCX, or TXT) and ingest it into the knowledge graph.
    Text is extracted automatically from the binary content.
    """
    content_bytes = await file.read()
    filename = file.filename or "upload"

    try:
        text = parse_file(filename, content_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from the uploaded file.",
        )

    doc_title = title or filename
    ingester = DocumentIngester(db)
    doc_id = ingester.ingest_document(
        title=doc_title,
        source_type=source_type,
        content=text,
        uploaded_by=uploaded_by,
        sensitivity_level=sensitivity_level,
        file_path=filename,
        mime_type=file.content_type,
        summary=summary,
    )
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document ingestion failed.")

    extraction = None
    if auto_extract:
        extractor = EntityRelationExtractor(db)
        raw = extractor.process_document(doc_id)
        extraction = {
            "entities": len(raw["entities"]),
            "concepts": len(raw["concepts"]),
            "relationships": len(raw["relationships"]),
        }

    return IngestResponse(document_id=doc_id, status="ingested", extraction=extraction)


# ── Documents — URL ingest ────────────────────────────────────────────────────

@app.post(
    "/api/v1/documents/ingest-url",
    tags=["Documents"],
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
)
def ingest_url(
    body: IngestUrlRequest,
    db: DatabaseConnection = Depends(get_db),
) -> IngestResponse:
    """
    Fetch a public URL, extract its text, and ingest it as a document.
    The page ``<title>`` tag is used as the document title if none is provided.
    """
    try:
        text, page_title = parse_url(body.url)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text content found at the provided URL.",
        )

    doc_title = body.title or page_title or body.url
    ingester = DocumentIngester(db)
    doc_id = ingester.ingest_document(
        title=doc_title,
        source_type=body.source_type,
        content=text,
        uploaded_by=body.uploaded_by,
        sensitivity_level=body.sensitivity_level,
        file_path=body.url,
        summary=body.summary,
    )
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document ingestion failed.")

    extraction = None
    if body.auto_extract:
        extractor = EntityRelationExtractor(db)
        raw = extractor.process_document(doc_id)
        extraction = {
            "entities": len(raw["entities"]),
            "concepts": len(raw["concepts"]),
            "relationships": len(raw["relationships"]),
        }

    return IngestResponse(document_id=doc_id, status="ingested", extraction=extraction)


# ── Documents — list ──────────────────────────────────────────────────────────

@app.get(
    "/api/v1/documents",
    tags=["Documents"],
    dependencies=[Depends(require_api_key)],
)
def list_documents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    source_type: Optional[str] = Query(default=None),
    sensitivity_level: Optional[str] = Query(default=None),
    db: DatabaseConnection = Depends(get_db),
) -> Dict[str, Any]:
    """List documents with optional filtering and pagination."""
    filters = ["is_archived = FALSE"]
    params: List[Any] = []

    if source_type:
        filters.append("source_type = %s")
        params.append(source_type)
    if sensitivity_level:
        filters.append("sensitivity_level = %s")
        params.append(sensitivity_level)

    where = " AND ".join(filters)
    params.extend([limit, skip])

    try:
        with db.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT document_id, title, source_type, sensitivity_level,
                       is_archived, file_size_bytes,
                       TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at
                FROM omnigraph.documents
                WHERE {where}
                ORDER BY document_id DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            cols = [
                "document_id", "title", "source_type", "sensitivity_level",
                "is_archived", "file_size_bytes", "created_at",
            ]
            docs = [dict(zip(cols, row)) for row in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) FROM omnigraph.documents WHERE {where}",
                params[:-2],
            )
            total = cur.fetchone()[0]
    except psycopg2.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"total": total, "skip": skip, "limit": limit, "documents": docs}


# ── Documents — detail ────────────────────────────────────────────────────────

@app.get(
    "/api/v1/documents/{doc_id}",
    tags=["Documents"],
    dependencies=[Depends(require_api_key)],
)
def get_document(
    doc_id: int,
    db: DatabaseConnection = Depends(get_db),
) -> Dict[str, Any]:
    """Fetch full document details including content."""
    try:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id, title, source_type, sensitivity_level,
                       is_archived, file_size_bytes, content, summary, content_hash,
                       TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at
                FROM omnigraph.documents
                WHERE document_id = %s
                """,
                (doc_id,),
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not row:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")

    cols = [
        "document_id", "title", "source_type", "sensitivity_level",
        "is_archived", "file_size_bytes", "content", "summary", "content_hash", "created_at",
    ]
    return dict(zip(cols, row))


# ── Documents — archive ───────────────────────────────────────────────────────

@app.delete(
    "/api/v1/documents/{doc_id}",
    tags=["Documents"],
    dependencies=[Depends(require_api_key)],
)
def archive_document(
    doc_id: int,
    db: DatabaseConnection = Depends(get_db),
) -> Dict[str, Any]:
    """Soft-delete (archive) a document. Content is preserved for audit purposes."""
    ingester = DocumentIngester(db)
    ok = ingester.set_document_archived(doc_id, archived=True)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")
    return {"document_id": doc_id, "status": "archived"}


# ── Search ────────────────────────────────────────────────────────────────────

@app.post(
    "/api/v1/search",
    tags=["Search"],
    response_model=SearchResponse,
    dependencies=[Depends(require_api_key)],
)
def search(
    body: SearchRequest,
    db: DatabaseConnection = Depends(get_db),
) -> SearchResponse:
    """
    Search the knowledge graph using one of four strategies:
    - **hybrid** (default): weighted blend of fulltext + semantic + graph
    - **fulltext**: PostgreSQL full-text search
    - **semantic**: vector similarity via Voyage AI embeddings
    - **graph**: entity-graph traversal
    """
    engine = SemanticQueryEngine(db, user_id=body.user_id)
    results = engine.search(body.query, strategy=body.strategy, limit=body.limit)

    # Filter to documents the requesting user can read
    acl = AccessControlManager(db)
    readable = [
        r for r in results
        if r.get("document_id") is not None
        and acl.check_access(body.user_id, "document", r["document_id"], "read")
    ]

    return SearchResponse(results=readable, count=len(readable), strategy=body.strategy)


# ── Chat (Agentic RAG) ────────────────────────────────────────────────────────

@app.post(
    "/api/v1/chat",
    tags=["Chat"],
    response_model=ChatResponse,
    dependencies=[Depends(require_api_key)],
)
def chat(
    body: ChatRequest,
    db: DatabaseConnection = Depends(get_db),
) -> ChatResponse:
    """
    Ask a natural-language question. The Claude agent searches the knowledge graph,
    reads relevant documents, and returns a cited answer.

    Requires ``ANTHROPIC_API_KEY`` to be set.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured. Chat is unavailable.",
        )

    try:
        agent = AnthropicOmniGraphAgent(db, user_id=body.user_id)
        result = agent.run(body.message)
    except Exception as exc:
        logger.error("Agent error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return ChatResponse(
        answer=result["answer"],
        citations=result["citations"],
        tools_used=result["tools_used"],
    )


# ── Graph — stats ─────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/graph/stats",
    tags=["Graph"],
    dependencies=[Depends(require_api_key)],
)
def graph_stats(db: DatabaseConnection = Depends(get_db)) -> Dict[str, Any]:
    """Return aggregate counts for the knowledge graph."""
    builder = KnowledgeGraphBuilder(db)
    return builder.get_graph_stats()


# ── Graph — list entities ─────────────────────────────────────────────────────

@app.get(
    "/api/v1/graph/entities",
    tags=["Graph"],
    dependencies=[Depends(require_api_key)],
)
def list_entities(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    entity_type: Optional[str] = Query(default=None),
    db: DatabaseConnection = Depends(get_db),
) -> Dict[str, Any]:
    """List all entities in the knowledge graph with optional type filtering."""
    params: List[Any] = []
    where = "1=1"
    if entity_type:
        where = "entity_type = %s"
        params.append(entity_type)
    params.extend([limit, skip])

    try:
        with db.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT entity_id, name, entity_type, confidence, description
                FROM omnigraph.entities
                WHERE {where}
                ORDER BY confidence DESC, entity_id
                LIMIT %s OFFSET %s
                """,
                params,
            )
            cols = ["entity_id", "name", "entity_type", "confidence", "description"]
            entities = [dict(zip(cols, row)) for row in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) FROM omnigraph.entities WHERE {where}",
                params[:-2],
            )
            total = cur.fetchone()[0]
    except psycopg2.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"total": total, "skip": skip, "limit": limit, "entities": entities}


# ── Graph — entity neighborhood ───────────────────────────────────────────────

@app.get(
    "/api/v1/graph/entities/{entity_id}/neighborhood",
    tags=["Graph"],
    dependencies=[Depends(require_api_key)],
)
def entity_neighborhood(
    entity_id: int,
    max_depth: int = Query(default=2, ge=1, le=4),
    db: DatabaseConnection = Depends(get_db),
) -> NeighborhoodResponse:
    """
    Return the N-hop neighborhood of an entity — all directly and indirectly
    related entities up to ``max_depth`` hops away.
    """
    builder = KnowledgeGraphBuilder(db)
    neighbors = builder.get_entity_neighborhood(entity_id, max_depth=max_depth)
    return NeighborhoodResponse(entity_id=entity_id, neighbors=neighbors)


# ── Graph — build / backfill ──────────────────────────────────────────────────

@app.post(
    "/api/v1/graph/build",
    tags=["Graph"],
    dependencies=[Depends(require_api_key)],
)
def build_graph(db: DatabaseConnection = Depends(get_db)) -> BuildGraphResponse:
    """
    Scan all documents that have not yet been entity-extracted and process them.
    Also detects duplicate entity nodes and returns updated graph statistics.

    This is a long-running operation for large corpora — call it after bulk ingestion.
    """
    extractor = EntityRelationExtractor(db)
    builder = KnowledgeGraphBuilder(db)
    result = builder.build_graph(extractor=extractor)

    return BuildGraphResponse(
        stats=result["stats"],
        duplicates_detected=result["duplicates_detected"],
        documents_newly_extracted=result["documents_newly_extracted"],
    )
