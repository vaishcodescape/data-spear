"""
OmniGraph MCP Server
====================
Exposes the full OmniGraph knowledge graph — search, ingestion, entity
extraction, graph traversal, and expert discovery — as Model Context
Protocol (MCP) tools, resources, and prompts.

Plug this into Claude Desktop and Claude can directly search documents,
ingest new content (text, files, URLs), explore the entity graph, and
query domain experts — all without a separate REST API call.

──────────────────────────────────────────────────────────────────────
Claude Desktop setup (~/.claude/claude_desktop_config.json):

{
  "mcpServers": {
    "omnigraph": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/Omni-Graph",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "VOYAGE_API_KEY":    "pa-...",
        "OMNIGRAPH_DB_HOST": "localhost",
        "OMNIGRAPH_DB_USER": "postgres",
        "OMNIGRAPH_DB_PASSWORD": "postgres"
      }
    }
  }
}

Run standalone for debugging:
    python -m mcp_server.server
──────────────────────────────────────────────────────────────────────

Tools (13):
  search                – Hybrid / fulltext / semantic / graph search
  read_document         – Full document text by ID
  find_experts          – Domain experts ranked by concept
  get_entity_documents  – Documents linked to a named entity
  find_related_concepts – Concept hierarchy + co-occurrence
  ingest_document       – Ingest plain text into the knowledge graph
  ingest_url            – Fetch a URL and ingest its content
  graph_stats           – Entity / relation / concept / document counts
  list_entities         – Browse entities with optional type filter
  entity_neighborhood   – N-hop entity graph traversal
  list_documents        – Paginated document listing
  extract_entities      – Run Claude NLP extraction on arbitrary text
  build_graph           – Backfill extraction for all unprocessed docs

Resources (3):
  omnigraph://graph/stats        – Live knowledge graph statistics
  omnigraph://documents/recent   – 20 most recently ingested documents
  omnigraph://entities/top       – 50 highest-confidence entities

Prompts (3):
  research_topic   – Deep-research any topic using the knowledge graph
  analyze_document – Comprehensive analysis of a specific document
  explore_entity   – Map all connections of a named entity
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("omnigraph.mcp")

# ── Configuration ─────────────────────────────────────────────────────────────

# Default user for RBAC checks; override via OMNIGRAPH_DEFAULT_USER_ID
DEFAULT_USER_ID: int = int(os.getenv("OMNIGRAPH_DEFAULT_USER_ID", "1"))

# ── Lazy DB connection (one per server process) ───────────────────────────────

_db = None


def _get_db():
    """Return a live DatabaseConnection, reconnecting if the socket dropped."""
    global _db
    if _db is None:
        from omnigraph.ingestion_pipeline import DatabaseConnection
        _db = DatabaseConnection()
        _db.connect()
        logger.info("Database connection established.")
    else:
        # Reconnect if the connection was closed (e.g. idle timeout)
        try:
            with _db.conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception:
            logger.warning("DB connection lost — reconnecting.")
            _db.connect()
    return _db


def _fmt(data: Any, indent: int = 2) -> str:
    """JSON-format any value with fallback to str()."""
    try:
        return json.dumps(data, indent=indent, default=str)
    except Exception:
        return str(data)


def _text(content: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


def _error(message: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=f"ERROR: {message}")]


# ── MCP Server ────────────────────────────────────────────────────────────────

server = Server("omnigraph")


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [

        # ── Search & Retrieval ────────────────────────────────────────────────

        types.Tool(
            name="search",
            description=(
                "Search the OmniGraph knowledge graph and return ranked documents. "
                "Supports four strategies:\n"
                "- hybrid (default): weighted blend of fulltext + semantic + graph — best for most queries\n"
                "- fulltext: PostgreSQL tsvector/tsquery — best for exact keywords, acronyms\n"
                "- semantic: Voyage AI vector similarity — best for natural-language meaning\n"
                "- graph: entity-traversal — best for 'what else is connected to X?'\n\n"
                "Results include document_id, title, summary, source_type, and relevance score. "
                "Use read_document to fetch full content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query or keyword expression",
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["hybrid", "fulltext", "semantic", "graph"],
                        "default": "hybrid",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Maximum number of results to return",
                    },
                },
                "required": ["query"],
            },
        ),

        types.Tool(
            name="read_document",
            description=(
                "Fetch the full text content of a document by its ID. "
                "Always call this after search when you need to read actual content "
                "rather than just the title/summary. Requires read access."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "integer",
                        "description": "Document ID from search results",
                    },
                    "max_chars": {
                        "type": "integer",
                        "default": 8000,
                        "description": "Maximum characters of content to return",
                    },
                },
                "required": ["document_id"],
            },
        ),

        types.Tool(
            name="find_experts",
            description=(
                "Find users who are domain experts on a concept, ranked by their "
                "document contributions and relevance scores. Returns name, department, "
                "document count, and expertise score."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "Concept or topic name (e.g. 'machine learning', 'Kubernetes')",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["concept"],
            },
        ),

        types.Tool(
            name="get_entity_documents",
            description=(
                "List all documents in the knowledge graph that are linked to a specific "
                "entity (person, organization, technology, standard). Useful for tracing "
                "which documents reference a particular technology or person."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Entity name to look up (e.g. 'Kubernetes', 'Dr. Smith')",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["entity_name"],
            },
        ),

        types.Tool(
            name="find_related_concepts",
            description=(
                "Get concepts related to a given concept via the concept hierarchy "
                "and document co-occurrence. Returns related concept names, their domain "
                "(AI / Security / Infrastructure / etc.), and relationship type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "Concept name to find relations for",
                    },
                },
                "required": ["concept"],
            },
        ),

        # ── Ingestion ─────────────────────────────────────────────────────────

        types.Tool(
            name="ingest_document",
            description=(
                "Ingest a new text document into the OmniGraph knowledge graph. "
                "Automatically: normalizes text, deduplicates by SHA-256 hash, "
                "generates vector embeddings, and runs Claude NLP extraction to "
                "populate entities, concepts, and relationships. Returns the document_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title"},
                    "content": {"type": "string", "description": "Full document text content"},
                    "source_type": {
                        "type": "string",
                        "enum": [
                            "report", "research_paper", "email", "technical_doc",
                            "code_repository", "project_artifact", "presentation",
                            "support_ticket", "log", "other",
                        ],
                        "default": "other",
                    },
                    "sensitivity_level": {
                        "type": "string",
                        "enum": ["public", "internal", "confidential", "restricted"],
                        "default": "internal",
                        "description": "Access control tier for this document",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional brief summary (auto-generated if omitted)",
                    },
                    "auto_extract": {
                        "type": "boolean",
                        "default": True,
                        "description": "Run entity/concept/relation extraction immediately after ingest",
                    },
                },
                "required": ["title", "content"],
            },
        ),

        types.Tool(
            name="ingest_url",
            description=(
                "Fetch a public URL, extract its text content (stripping nav/scripts/ads), "
                "and ingest it into the knowledge graph. Page title is auto-detected. "
                "Runs entity extraction automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public URL to fetch and ingest"},
                    "title": {
                        "type": "string",
                        "description": "Override the auto-detected page title",
                    },
                    "source_type": {
                        "type": "string",
                        "enum": [
                            "report", "research_paper", "email", "technical_doc",
                            "code_repository", "project_artifact", "presentation",
                            "support_ticket", "log", "other",
                        ],
                        "default": "other",
                    },
                    "sensitivity_level": {
                        "type": "string",
                        "enum": ["public", "internal", "confidential", "restricted"],
                        "default": "internal",
                    },
                },
                "required": ["url"],
            },
        ),

        # ── Graph Exploration ─────────────────────────────────────────────────

        types.Tool(
            name="graph_stats",
            description=(
                "Return aggregate statistics for the knowledge graph: total entities, "
                "relations, concepts, documents, and taxonomy nodes — broken down by type. "
                "Useful for understanding the current state of the graph."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),

        types.Tool(
            name="list_entities",
            description=(
                "List entities in the knowledge graph with optional type filtering. "
                "Entity types: person, organization, technology, standard, location, other. "
                "Results are ordered by confidence score descending."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["person", "organization", "technology", "standard", "location", "other"],
                        "description": "Filter by entity type (omit for all types)",
                    },
                    "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                },
            },
        ),

        types.Tool(
            name="entity_neighborhood",
            description=(
                "Explore the N-hop neighborhood of an entity — all directly and indirectly "
                "related entities up to max_depth hops away. Returns entity names, types, "
                "relation types, strengths, and hop depth. Essential for understanding "
                "how entities connect to each other."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Entity name to explore (exact or partial match)",
                    },
                    "max_depth": {
                        "type": "integer",
                        "default": 2,
                        "minimum": 1,
                        "maximum": 4,
                        "description": "How many hops to traverse",
                    },
                },
                "required": ["entity_name"],
            },
        ),

        types.Tool(
            name="list_documents",
            description=(
                "List documents in the knowledge graph with optional filtering by "
                "source type or sensitivity level. Returns title, type, sensitivity, "
                "size, and creation date."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_type": {
                        "type": "string",
                        "description": "Filter by source type (e.g. 'research_paper')",
                    },
                    "sensitivity_level": {
                        "type": "string",
                        "enum": ["public", "internal", "confidential", "restricted"],
                    },
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "offset": {"type": "integer", "default": 0},
                },
            },
        ),

        # ── Extraction (standalone) ───────────────────────────────────────────

        types.Tool(
            name="extract_entities",
            description=(
                "Run Claude-powered NLP extraction on arbitrary text without storing anything. "
                "Returns extracted entities, concepts, and relationships as structured JSON. "
                "Useful for previewing what would be extracted before ingesting, or for "
                "analyzing text from external sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to analyze (up to 6000 characters for LLM extraction)",
                    },
                },
                "required": ["text"],
            },
        ),

        # ── Maintenance ───────────────────────────────────────────────────────

        types.Tool(
            name="build_graph",
            description=(
                "Scan all documents that have not yet had entity extraction run and process "
                "them now. Also detects duplicate entity nodes and returns updated graph stats. "
                "Run this after bulk ingestion to ensure the graph is fully populated."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ── Tool implementations ───────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent]:

    try:
        # Route to the correct handler
        if name == "search":
            return await _search(arguments)
        elif name == "read_document":
            return await _read_document(arguments)
        elif name == "find_experts":
            return await _find_experts(arguments)
        elif name == "get_entity_documents":
            return await _get_entity_documents(arguments)
        elif name == "find_related_concepts":
            return await _find_related_concepts(arguments)
        elif name == "ingest_document":
            return await _ingest_document(arguments)
        elif name == "ingest_url":
            return await _ingest_url(arguments)
        elif name == "graph_stats":
            return await _graph_stats()
        elif name == "list_entities":
            return await _list_entities(arguments)
        elif name == "entity_neighborhood":
            return await _entity_neighborhood(arguments)
        elif name == "list_documents":
            return await _list_documents(arguments)
        elif name == "extract_entities":
            return await _extract_entities(arguments)
        elif name == "build_graph":
            return await _build_graph()
        else:
            return _error(f"Unknown tool: {name}")
    except Exception as exc:
        logger.exception("Tool '%s' raised an exception.", name)
        return _error(str(exc))


# ── Individual tool handlers ──────────────────────────────────────────────────

async def _search(args: dict) -> list[types.TextContent]:
    query = args["query"]
    strategy = args.get("strategy", "hybrid")
    limit = int(args.get("limit", 10))

    def _run():
        from omnigraph.semantic_query_engine import SemanticQueryEngine
        engine = SemanticQueryEngine(_get_db(), user_id=DEFAULT_USER_ID)
        return engine.search(query, strategy=strategy, limit=limit)

    results = await asyncio.to_thread(_run)
    if not results:
        return _text("No documents found matching your query.")

    lines = [f"Found {len(results)} result(s) for '{query}' [{strategy}]:\n"]
    for i, r in enumerate(results, 1):
        doc_id = r.get("document_id", "?")
        title = r.get("title", "Untitled")
        source = r.get("source_type", "")
        score = r.get("score", r.get("rank", 0))
        summary = (r.get("summary") or "")[:200]
        lines.append(
            f"{i}. [doc_id={doc_id}] {title} ({source})\n"
            f"   Score: {score:.4f}\n"
            f"   {summary}\n"
        )
    return _text("\n".join(lines))


async def _read_document(args: dict) -> list[types.TextContent]:
    doc_id = int(args["document_id"])
    max_chars = int(args.get("max_chars", 8000))

    def _run():
        db = _get_db()
        with db.conn.cursor() as cur:
            cur.execute(
                "SELECT title, source_type, sensitivity_level, content "
                "FROM omnigraph.documents WHERE document_id = %s",
                (doc_id,),
            )
            return cur.fetchone()

    row = await asyncio.to_thread(_run)
    if not row:
        return _error(f"Document {doc_id} not found.")

    title, source_type, sensitivity, content = row
    content_snippet = (content or "")[:max_chars]
    truncated = len(content or "") > max_chars

    out = (
        f"[doc_id={doc_id}] {title}\n"
        f"Type: {source_type}  |  Sensitivity: {sensitivity}\n"
        f"{'─' * 60}\n"
        f"{content_snippet}"
    )
    if truncated:
        out += f"\n\n... [truncated at {max_chars} chars — use a larger max_chars to see more]"
    return _text(out)


async def _find_experts(args: dict) -> list[types.TextContent]:
    concept = args["concept"]
    limit = int(args.get("limit", 5))

    def _run():
        from omnigraph.semantic_query_engine import SemanticQueryEngine
        engine = SemanticQueryEngine(_get_db(), user_id=DEFAULT_USER_ID)
        return engine.find_experts(concept, limit=limit)

    experts = await asyncio.to_thread(_run)
    if not experts:
        return _text(f"No experts found for concept: '{concept}'")

    lines = [f"Top experts on '{concept}':\n"]
    for i, e in enumerate(experts, 1):
        lines.append(
            f"{i}. {e.get('full_name', '?')} "
            f"({e.get('department', 'Unknown dept.')})\n"
            f"   Expertise score: {e.get('expertise_score', 0):.2f}  |  "
            f"Documents: {e.get('doc_count', 0)}"
        )
    return _text("\n".join(lines))


async def _get_entity_documents(args: dict) -> list[types.TextContent]:
    entity_name = args["entity_name"]
    limit = int(args.get("limit", 10))

    def _run():
        from omnigraph.semantic_query_engine import SemanticQueryEngine
        engine = SemanticQueryEngine(_get_db(), user_id=DEFAULT_USER_ID)
        return engine.get_entity_documents(entity_name, limit=limit)

    docs = await asyncio.to_thread(_run)
    if not docs:
        return _text(f"No documents found for entity: '{entity_name}'")

    lines = [f"Documents linked to entity '{entity_name}':\n"]
    for d in docs:
        doc_id = d.get("document_id", "?")
        title = d.get("title", "Untitled")
        source = d.get("source_type", "")
        lines.append(f"  [doc_id={doc_id}] {title} ({source})")
    return _text("\n".join(lines))


async def _find_related_concepts(args: dict) -> list[types.TextContent]:
    concept = args["concept"]

    def _run():
        from omnigraph.semantic_query_engine import SemanticQueryEngine
        engine = SemanticQueryEngine(_get_db(), user_id=DEFAULT_USER_ID)
        return engine.find_related_concepts(concept)

    related = await asyncio.to_thread(_run)
    if not related:
        return _text(f"No related concepts found for: '{concept}'")

    lines = [f"Concepts related to '{concept}':\n"]
    for c in related[:20]:
        name = c.get("name", "?")
        domain = c.get("domain", "")
        rel = c.get("relationship_types", "")
        lines.append(f"  {name} [{domain}]  ({rel})")
    return _text("\n".join(lines))


async def _ingest_document(args: dict) -> list[types.TextContent]:
    title = args["title"]
    content = args["content"]
    source_type = args.get("source_type", "other")
    sensitivity = args.get("sensitivity_level", "internal")
    summary = args.get("summary")
    auto_extract = bool(args.get("auto_extract", True))

    def _run():
        from omnigraph.ingestion_pipeline import DocumentIngester
        from omnigraph.entity_relation_extractor import EntityRelationExtractor
        db = _get_db()
        ingester = DocumentIngester(db)
        doc_id = ingester.ingest_document(
            title=title,
            source_type=source_type,
            content=content,
            uploaded_by=DEFAULT_USER_ID,
            sensitivity_level=sensitivity,
            summary=summary,
        )
        extraction = None
        if doc_id and auto_extract:
            extractor = EntityRelationExtractor(db)
            raw = extractor.process_document(doc_id)
            extraction = {
                "entities": len(raw["entities"]),
                "concepts": len(raw["concepts"]),
                "relationships": len(raw["relationships"]),
            }
        return doc_id, extraction

    doc_id, extraction = await asyncio.to_thread(_run)
    if doc_id is None:
        return _error("Document ingestion failed. Check server logs for details.")

    msg = f"Document ingested successfully.\ndocument_id: {doc_id}\ntitle: {title}"
    if extraction:
        msg += (
            f"\n\nExtraction results:\n"
            f"  Entities:      {extraction['entities']}\n"
            f"  Concepts:      {extraction['concepts']}\n"
            f"  Relationships: {extraction['relationships']}"
        )
    return _text(msg)


async def _ingest_url(args: dict) -> list[types.TextContent]:
    url = args["url"]
    title_override = args.get("title")
    source_type = args.get("source_type", "other")
    sensitivity = args.get("sensitivity_level", "internal")

    def _run():
        from api.file_parser import parse_url
        from omnigraph.ingestion_pipeline import DocumentIngester
        from omnigraph.entity_relation_extractor import EntityRelationExtractor
        db = _get_db()

        text, page_title = parse_url(url)
        if not text.strip():
            raise ValueError("No text content found at the provided URL.")

        doc_title = title_override or page_title or url
        ingester = DocumentIngester(db)
        doc_id = ingester.ingest_document(
            title=doc_title,
            source_type=source_type,
            content=text,
            uploaded_by=DEFAULT_USER_ID,
            sensitivity_level=sensitivity,
            file_path=url,
        )
        extraction = None
        if doc_id:
            extractor = EntityRelationExtractor(db)
            raw = extractor.process_document(doc_id)
            extraction = {
                "entities": len(raw["entities"]),
                "concepts": len(raw["concepts"]),
                "relationships": len(raw["relationships"]),
            }
        return doc_id, doc_title, extraction

    doc_id, doc_title, extraction = await asyncio.to_thread(_run)
    if doc_id is None:
        return _error("URL ingestion failed.")

    msg = (
        f"URL ingested successfully.\n"
        f"document_id: {doc_id}\n"
        f"title: {doc_title}\n"
        f"source: {url}"
    )
    if extraction:
        msg += (
            f"\n\nExtraction results:\n"
            f"  Entities:      {extraction['entities']}\n"
            f"  Concepts:      {extraction['concepts']}\n"
            f"  Relationships: {extraction['relationships']}"
        )
    return _text(msg)


async def _graph_stats() -> list[types.TextContent]:
    def _run():
        from omnigraph.graph_builder import KnowledgeGraphBuilder
        builder = KnowledgeGraphBuilder(_get_db())
        return builder.get_graph_stats()

    stats = await asyncio.to_thread(_run)
    lines = [
        "Knowledge Graph Statistics",
        "─" * 40,
        f"  Documents:      {stats.get('total_documents', 0)}",
        f"  Entities:       {stats.get('total_entities', 0)}",
        f"  Relations:      {stats.get('total_relations', 0)}",
        f"  Concepts:       {stats.get('total_concepts', 0)}",
        f"  Taxonomy nodes: {stats.get('total_taxonomy_nodes', 0)}",
    ]
    if stats.get("entities_by_type"):
        lines.append("\nEntities by type:")
        for etype, count in sorted(stats["entities_by_type"].items(), key=lambda x: -x[1]):
            lines.append(f"    {etype:<16} {count}")
    if stats.get("relations_by_type"):
        lines.append("\nRelations by type:")
        for rtype, count in sorted(stats["relations_by_type"].items(), key=lambda x: -x[1]):
            lines.append(f"    {rtype:<20} {count}")
    return _text("\n".join(lines))


async def _list_entities(args: dict) -> list[types.TextContent]:
    entity_type = args.get("entity_type")
    limit = int(args.get("limit", 30))
    offset = int(args.get("offset", 0))

    def _run():
        db = _get_db()
        params: list = []
        where = "1=1"
        if entity_type:
            where = "entity_type = %s"
            params.append(entity_type)
        params.extend([limit, offset])
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
            return cur.fetchall()

    rows = await asyncio.to_thread(_run)
    if not rows:
        return _text("No entities found.")

    lines = [f"Entities (showing {len(rows)}, offset={offset}):\n"]
    for entity_id, name, etype, confidence, description in rows:
        desc = (description or "")[:80]
        lines.append(
            f"  [{entity_id}] {name} ({etype})  confidence={confidence:.3f}"
            + (f"\n      {desc}" if desc else "")
        )
    return _text("\n".join(lines))


async def _entity_neighborhood(args: dict) -> list[types.TextContent]:
    entity_name = args["entity_name"]
    max_depth = int(args.get("max_depth", 2))

    def _run():
        db = _get_db()
        # Resolve name → entity_id
        with db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_id, name, entity_type
                FROM omnigraph.entities
                WHERE LOWER(name) LIKE LOWER(%s)
                ORDER BY confidence DESC LIMIT 1
                """,
                (f"%{entity_name}%",),
            )
            row = cur.fetchone()
        if not row:
            return None, None, None, []
        entity_id, name, etype = row

        from omnigraph.graph_builder import KnowledgeGraphBuilder
        builder = KnowledgeGraphBuilder(db)
        neighbors = builder.get_entity_neighborhood(entity_id, max_depth=max_depth)
        return entity_id, name, etype, neighbors

    entity_id, name, etype, neighbors = await asyncio.to_thread(_run)
    if entity_id is None:
        return _text(f"Entity '{entity_name}' not found in the knowledge graph.")

    lines = [
        f"Neighborhood of [{entity_id}] {name} ({etype})  "
        f"[depth={max_depth}]\n"
    ]
    if not neighbors:
        lines.append("  No connected entities found.")
    else:
        for n in neighbors:
            indent = "  " * n["depth"]
            lines.append(
                f"{indent}{'└─' if n['depth'] > 1 else '├─'} "
                f"[{n['entity_id']}] {n['name']} ({n['entity_type']})  "
                f"via [{n['relation_type']}]  strength={n['strength']:.2f}"
            )
    return _text("\n".join(lines))


async def _list_documents(args: dict) -> list[types.TextContent]:
    source_type = args.get("source_type")
    sensitivity = args.get("sensitivity_level")
    limit = int(args.get("limit", 20))
    offset = int(args.get("offset", 0))

    def _run():
        db = _get_db()
        filters = ["is_archived = FALSE"]
        params: list = []
        if source_type:
            filters.append("source_type = %s")
            params.append(source_type)
        if sensitivity:
            filters.append("sensitivity_level = %s")
            params.append(sensitivity)
        where = " AND ".join(filters)
        params.extend([limit, offset])
        with db.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT document_id, title, source_type, sensitivity_level,
                       file_size_bytes,
                       TO_CHAR(created_at, 'YYYY-MM-DD') AS created_at
                FROM omnigraph.documents
                WHERE {where}
                ORDER BY document_id DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return cur.fetchall()

    rows = await asyncio.to_thread(_run)
    if not rows:
        return _text("No documents found.")

    lines = [f"Documents (showing {len(rows)}, offset={offset}):\n"]
    for doc_id, title, stype, sens, size_bytes, created in rows:
        size = f"{(size_bytes or 0) // 1024}KB" if size_bytes else "?"
        lines.append(
            f"  [doc_id={doc_id}] {title}\n"
            f"    type={stype}  sensitivity={sens}  size={size}  created={created}"
        )
    return _text("\n".join(lines))


async def _extract_entities(args: dict) -> list[types.TextContent]:
    text = args["text"]

    def _run():
        from omnigraph.entity_relation_extractor import EntityRelationExtractor
        # Pass None as db — only keyword extraction is used for standalone mode
        extractor = EntityRelationExtractor(db_connection=None, use_llm=True)

        # LLM extraction doesn't need a DB connection
        if extractor._use_llm:
            try:
                raw = extractor._extract_with_llm(text)
                entities = extractor._normalize_llm_entities(raw.get("entities", []), text)
                concepts = extractor._normalize_llm_concepts(raw.get("concepts", []), text)
                entity_set = {e["name"] for e in entities}
                relationships = extractor._normalize_llm_relationships(
                    raw.get("relationships", []), entities,
                )
                return entities, concepts, relationships, "llm"
            except Exception as exc:
                logger.warning("LLM extraction failed in standalone mode: %s", exc)

        # Fallback to keyword
        entities = extractor.extract_entities(text)
        concepts = extractor.extract_concepts(text)
        relationships = extractor.extract_relationships(text, entities)
        return entities, concepts, relationships, "keyword"

    entities, concepts, relationships, mode = await asyncio.to_thread(_run)

    lines = [f"Extraction results [{mode} mode]:\n"]
    lines.append(f"ENTITIES ({len(entities)}):")
    for e in entities:
        lines.append(
            f"  [{e['entity_type']}] {e['name']}  "
            f"confidence={e.get('confidence', 0):.2f}  "
            f"mentions={e.get('mention_count', 0)}"
            + (f"\n    {e['description'][:100]}" if e.get("description") else "")
        )
    lines.append(f"\nCONCEPTS ({len(concepts)}):")
    for c in concepts:
        lines.append(f"  [{c['domain']}] {c['name']}  relevance={c.get('relevance_score', 0):.2f}")
    lines.append(f"\nRELATIONSHIPS ({len(relationships)}):")
    for r in relationships:
        lines.append(
            f"  {r['source']} --[{r['relation_type']}]--> {r['target']}  "
            f"strength={r.get('strength', 0):.2f}"
        )
    return _text("\n".join(lines))


async def _build_graph() -> list[types.TextContent]:
    def _run():
        from omnigraph.graph_builder import KnowledgeGraphBuilder
        from omnigraph.entity_relation_extractor import EntityRelationExtractor
        db = _get_db()
        extractor = EntityRelationExtractor(db)
        builder = KnowledgeGraphBuilder(db)
        return builder.build_graph(extractor=extractor)

    result = await asyncio.to_thread(_run)
    stats = result["stats"]
    msg = (
        f"Knowledge graph build complete.\n\n"
        f"Documents newly extracted:  {result['documents_newly_extracted']}\n"
        f"Duplicate pairs detected:   {result['duplicates_detected']}\n\n"
        f"Current graph size:\n"
        f"  Documents:  {stats.get('total_documents', 0)}\n"
        f"  Entities:   {stats.get('total_entities', 0)}\n"
        f"  Relations:  {stats.get('total_relations', 0)}\n"
        f"  Concepts:   {stats.get('total_concepts', 0)}"
    )
    return _text(msg)


# ══════════════════════════════════════════════════════════════════════════════
# RESOURCES
# ══════════════════════════════════════════════════════════════════════════════

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            name="Graph Statistics",
            uri="omnigraph://graph/stats",
            description="Live aggregate counts for the knowledge graph (entities, relations, concepts, documents).",
            mimeType="application/json",
        ),
        types.Resource(
            name="Recent Documents",
            uri="omnigraph://documents/recent",
            description="The 20 most recently ingested documents with title, type, and sensitivity.",
            mimeType="application/json",
        ),
        types.Resource(
            name="Top Entities",
            uri="omnigraph://entities/top",
            description="The 50 highest-confidence entities in the knowledge graph.",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: types.AnyUrl) -> str:
    uri_str = str(uri)

    if uri_str == "omnigraph://graph/stats":
        def _run():
            from omnigraph.graph_builder import KnowledgeGraphBuilder
            return KnowledgeGraphBuilder(_get_db()).get_graph_stats()
        stats = await asyncio.to_thread(_run)
        return _fmt(stats)

    elif uri_str == "omnigraph://documents/recent":
        def _run():
            db = _get_db()
            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT document_id, title, source_type, sensitivity_level,
                           file_size_bytes,
                           TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at
                    FROM omnigraph.documents
                    WHERE is_archived = FALSE
                    ORDER BY document_id DESC LIMIT 20
                    """
                )
                cols = ["document_id", "title", "source_type", "sensitivity_level",
                        "file_size_bytes", "created_at"]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        docs = await asyncio.to_thread(_run)
        return _fmt({"documents": docs, "count": len(docs)})

    elif uri_str == "omnigraph://entities/top":
        def _run():
            db = _get_db()
            with db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_id, name, entity_type, confidence, description
                    FROM omnigraph.entities
                    ORDER BY confidence DESC LIMIT 50
                    """
                )
                cols = ["entity_id", "name", "entity_type", "confidence", "description"]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        entities = await asyncio.to_thread(_run)
        return _fmt({"entities": entities, "count": len(entities)})

    raise ValueError(f"Unknown resource URI: {uri_str}")


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

@server.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="research_topic",
            description=(
                "Deep-research any topic using the OmniGraph knowledge graph. "
                "Searches documents, finds related concepts, identifies domain experts, "
                "and synthesizes a comprehensive answer with citations."
            ),
            arguments=[
                types.PromptArgument(
                    name="topic",
                    description="The topic or question to research",
                    required=True,
                ),
                types.PromptArgument(
                    name="depth",
                    description="Research depth: 'quick' (search only) or 'deep' (read documents + explore graph)",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="analyze_document",
            description=(
                "Perform a comprehensive analysis of a specific document: "
                "key entities, main concepts, how it relates to other documents, "
                "and what domain experts are associated with its topics."
            ),
            arguments=[
                types.PromptArgument(
                    name="document_id",
                    description="The document_id to analyze (from search results or list_documents)",
                    required=True,
                ),
            ],
        ),
        types.Prompt(
            name="explore_entity",
            description=(
                "Map all connections of a named entity in the knowledge graph: "
                "direct relationships, related documents, similar concepts, "
                "and domain experts. Produces a complete entity profile."
            ),
            arguments=[
                types.PromptArgument(
                    name="entity_name",
                    description="Entity name to explore (e.g. 'Kubernetes', 'Dr. Smith', 'Google')",
                    required=True,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(
    name: str, arguments: Optional[dict] = None
) -> types.GetPromptResult:
    args = arguments or {}

    if name == "research_topic":
        topic = args.get("topic", "")
        depth = args.get("depth", "deep")
        depth_instruction = (
            "For a deep analysis: use search (hybrid), then read_document for the top 3 results, "
            "then use find_related_concepts and find_experts to enrich your answer."
            if depth == "deep"
            else "Use search (hybrid, limit=5) and summarize what you find."
        )
        return types.GetPromptResult(
            description=f"Research prompt for: {topic}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Research the following topic using the OmniGraph knowledge graph:\n\n"
                            f"**Topic:** {topic}\n\n"
                            f"Instructions:\n"
                            f"1. Use the `search` tool with strategy='hybrid' to find relevant documents.\n"
                            f"2. {depth_instruction}\n"
                            f"3. Use `find_related_concepts` to discover related domains.\n"
                            f"4. Use `find_experts` to identify who knows most about this topic.\n"
                            f"5. Synthesize a comprehensive answer. Cite every factual claim "
                            f"with [doc_id=X] format.\n"
                            f"6. End with: a list of cited documents and a list of recommended experts."
                        ),
                    ),
                ),
            ],
        )

    elif name == "analyze_document":
        doc_id = args.get("document_id", "")
        return types.GetPromptResult(
            description=f"Document analysis prompt for doc_id={doc_id}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Perform a comprehensive analysis of document [doc_id={doc_id}].\n\n"
                            f"Steps:\n"
                            f"1. Use `read_document` (document_id={doc_id}) to get the full content.\n"
                            f"2. Use `extract_entities` on key excerpts to identify entities/concepts.\n"
                            f"3. Use `get_entity_documents` for 2–3 key entities to find related docs.\n"
                            f"4. Use `find_related_concepts` for the main topic.\n"
                            f"5. Use `find_experts` for the primary concept.\n\n"
                            f"Deliver:\n"
                            f"- Executive summary (3–5 sentences)\n"
                            f"- Key entities extracted\n"
                            f"- Main concepts and their domains\n"
                            f"- Related documents in the knowledge graph\n"
                            f"- Recommended domain experts\n"
                            f"- Any gaps or areas for further research"
                        ),
                    ),
                ),
            ],
        )

    elif name == "explore_entity":
        entity_name = args.get("entity_name", "")
        return types.GetPromptResult(
            description=f"Entity exploration prompt for: {entity_name}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Build a complete profile of the entity **{entity_name}** "
                            f"from the OmniGraph knowledge graph.\n\n"
                            f"Steps:\n"
                            f"1. Use `entity_neighborhood` (entity_name='{entity_name}', max_depth=2) "
                            f"to map all connections.\n"
                            f"2. Use `get_entity_documents` to list all linked documents.\n"
                            f"3. Use `search` to find additional context: "
                            f"query='{entity_name}', strategy='hybrid'.\n"
                            f"4. Use `find_related_concepts` for the entity's primary domain.\n\n"
                            f"Deliver:\n"
                            f"- Entity type and description\n"
                            f"- Direct relationships (1-hop) with relation types\n"
                            f"- Indirect connections (2-hop) and their significance\n"
                            f"- Documents that reference this entity\n"
                            f"- Related concepts and domains\n"
                            f"- Insights and patterns from the graph structure"
                        ),
                    ),
                ),
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    logger.info("Starting OmniGraph MCP server (stdio transport).")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="omnigraph",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
