# FastAPI service exposing the Python agent to the bash CLI (scripts/data-spear.sh).
from __future__ import annotations

import json
import re
from collections.abc import Iterator

import psycopg2
import psycopg2.extensions
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from data_spear.config import settings
from data_spear.db import set_active_dsn
from data_spear.ingest import ingest_all
from data_spear.rag import RAG
from data_spear.vector_store import set_active_namespace


def require_auth(authorization: str | None = Header(default=None)) -> None:
    # Bearer-token gate; a no-op unless API_TOKEN is configured.
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


app = FastAPI(title="Data-Spear", version="1.0.0")
_rag: RAG | None = None


def _get_rag() -> RAG:
    global _rag
    if _rag is None:
        try:
            _rag = RAG()
        except RuntimeError as e:  # missing PINECONE/ANTHROPIC key
            raise HTTPException(status_code=503, detail=str(e)) from e
    return _rag


class ConnectRequest(BaseModel):
    # A full DSN/connection URL takes precedence; otherwise the components are used.
    dsn: str | None = None
    host: str = "localhost"
    port: int = 5432
    dbname: str = "postgres"
    user: str = "postgres"
    password: str = ""
    sslmode: str | None = None


class ConnectResponse(BaseModel):
    status: str
    database: str
    server: str


class QueryRequest(BaseModel):
    prompt: str
    top_k: int | None = None
    # User authorization for Tier 2 SQL (DDL, unbounded writes). Must come from a
    # deliberate user action (the CLI's `!` prefix / --destructive flag), never set by default.
    allow_destructive: bool = False


class Hit(BaseModel):
    id: str
    score: float
    text: str


class QueryResponse(BaseModel):
    answer: str
    hits: list[Hit]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/connect", response_model=ConnectResponse, dependencies=[Depends(require_auth)])
def connect_db(req: ConnectRequest) -> ConnectResponse:
    #Validate the supplied PostgreSQL credentials and make them the active connection.
    if req.dsn and req.dsn.strip():
        dsn = req.dsn.strip()
    else:
        kwargs: dict[str, str] = {
            "host": req.host,
            "port": str(req.port),
            "dbname": req.dbname,
            "user": req.user,
            "password": req.password,
        }
        if req.sslmode:
            kwargs["sslmode"] = req.sslmode
        dsn = psycopg2.extensions.make_dsn(**kwargs)

    # Test the connection before committing to it, so the user gets immediate feedback.
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), version()")
                row = cur.fetchone()
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not connect: {e}") from e

    database = str(row[0]) if row else req.dbname
    version = str(row[1]) if row else ""
    set_active_dsn(dsn)

    # Scope the vector index to this database so chunks ingested from one DB are
    # never served as context for another. New DB identity = fresh namespace
    # (which starts empty until /ingest runs against it).
    info = psycopg2.extensions.parse_dsn(dsn)
    raw_ns = (
        f"{info.get('host', 'local')}-{info.get('port', '5432')}-"
        f"{info.get('dbname', database)}"
    )
    set_active_namespace(re.sub(r"[^a-zA-Z0-9_-]", "-", raw_ns))

    server = version.split(" on ", 1)[0] if version else "PostgreSQL"
    return ConnectResponse(status="connected", database=database, server=server)


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_auth)])
def query(req: QueryRequest) -> QueryResponse:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    rag = _get_rag()
    result = rag.answer(
        req.prompt, top_k=req.top_k, allow_destructive=req.allow_destructive
    )
    hits = [
        Hit(
            id=str(h["id"]),
            score=float(h["score"] or 0.0),
            text=h["fields"].get("chunk_text", ""),
        )
        for h in result.hits
    ]
    return QueryResponse(answer=result.answer, hits=hits)


@app.post("/query/stream", dependencies=[Depends(require_auth)])
def query_stream(req: QueryRequest) -> StreamingResponse:
    # Run the agent and stream progress as Server-Sent Events.

    # Events mirror the agent loop: `retrieval`, `thinking`, `tool_use`,
    # `tool_result`, then a terminal `final` (or `error`).
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    rag = _get_rag()

    def gen() -> Iterator[str]:
        try:
            for evt in rag.answer_events(
                req.prompt, top_k=req.top_k, allow_destructive=req.allow_destructive
            ):
                if evt["type"] == "final":
                    evt = {
                        "type": "final",
                        "answer": evt["answer"],
                        "hits": [
                            {
                                "id": str(h["id"]),
                                "score": float(h["score"] or 0.0),
                                "text": h["fields"].get("chunk_text", ""),
                            }
                            for h in evt.get("hits", [])
                        ],
                    }
                yield f"data: {json.dumps(evt, default=str)}\n\n"
        except Exception as e:  # surface failures to the client instead of dropping the stream
            payload = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ingest", dependencies=[Depends(require_auth)])
def ingest() -> dict[str, int]:
    try:
        return ingest_all()
    except RuntimeError as e:  # e.g. no SOURCES configured
        raise HTTPException(status_code=400, detail=str(e)) from e


def run() -> None:
    # Console-script entry point (`data-spear-server`). The agent keeps the active
    # database connection in per-process state, so the server runs single-worker by
    # default; override HOST / PORT / UVICORN_WORKERS via the environment.
    import os

    import uvicorn

    uvicorn.run(
        "data_spear.api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        workers=int(os.environ.get("UVICORN_WORKERS", "1")),
    )
