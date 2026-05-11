<div align="center">

# OmniGraph

**Enterprise knowledge graph platform that transforms unstructured documents into a structured, searchable, AI-queryable graph.**

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-14191f?style=for-the-badge&logo=python&logoColor=3776AB)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-14191f?style=for-the-badge&logo=postgresql&logoColor=4169E1)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-14191f?style=for-the-badge&logo=fastapi&logoColor=009688)](https://fastapi.tiangolo.com/)
[![Anthropic](https://img.shields.io/badge/Claude_AI-14191f?style=for-the-badge&logo=anthropic&logoColor=D4A574)](https://www.anthropic.com/)
[![MCP](https://img.shields.io/badge/MCP_Server-14191f?style=for-the-badge&logo=anthropic&logoColor=8B5CF6)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-14191f?style=for-the-badge&logo=docker&logoColor=2496ED)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/MIT-14191f?style=for-the-badge&logo=opensourceinitiative&logoColor=22C55E)](LICENSE)

</div>

<br/>

Ingest PDFs, DOCX files, URLs, or raw text. OmniGraph parses, deduplicates, embeds, and extracts entities and relationships using Claude AI, then stores everything in a 19-table PostgreSQL schema with pgvector. Query the graph through four search strategies, a conversational RAG agent with citations, or plug it directly into Claude Desktop as an MCP server.

---

## System Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │                 Interface Layer                   │
                    │                                                   │
                    │   Claude Desktop       HTTP Clients     Terminal  │
                    │   (MCP Protocol)       (REST / JSON)    (ANSI)   │
                    └────────┬──────────────────┬───────────────┬──────┘
                             │                  │               │
                ┌────────────▼──────┐ ┌─────────▼────────┐ ┌───▼──────────┐
                │   MCP Server      │ │   FastAPI         │ │  Console App │
                │                   │ │                   │ │              │
                │   13 tools        │ │   14 endpoints    │ │  Interactive │
                │   3 resources     │ │   Swagger UI      │ │  menus       │
                │   3 prompts       │ │   API-key auth    │ │              │
                └────────┬──────────┘ └─────────┬────────┘ └───┬──────────┘
                         │                      │              │
            ┌────────────▼──────────────────────▼──────────────▼────────────┐
            │                        Core Engine                            │
            │                                                               │
            │  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐ │
            │  │  Ingestion    │  │  NLP Extractor │  │  Query Engine      │ │
            │  │  Pipeline     │  │  Claude Haiku  │  │  fulltext/semantic │ │
            │  │              │  │  + keyword      │  │  /graph/hybrid     │ │
            │  │  normalize    │  │  fallback       │  │                    │ │
            │  │  dedup (SHA)  │  │                 │  │  weighted ranker   │ │
            │  │  version      │  │  entities       │  │                    │ │
            │  └──────┬───────┘  │  concepts        │  └────────┬───────────┘ │
            │         │          │  relationships    │           │             │
            │  ┌──────▼───────┐  └────────┬────────┘  ┌────────▼───────────┐ │
            │  │  Embedder     │           │           │  Agentic RAG       │ │
            │  │  Voyage AI    │  ┌────────▼────────┐  │  Claude Opus       │ │
            │  │  voyage-3     │  │  Graph Builder   │  │  tool-use loop     │ │
            │  │  1024-dim     │  │  entity/relation │  │  cited answers     │ │
            │  └──────────────┘  │  CRUD + backfill  │  └──────────────────┘ │
            │                     └─────────────────┘                        │
            │  ┌───────────────────────────────────────────────────────────┐ │
            │  │                Access Control & Audit                     │ │
            │  │  RBAC with 4 sensitivity tiers (public -> restricted)     │ │
            │  │  Row-level enforcement at read time, immutable audit log  │ │
            │  └───────────────────────────────────────────────────────────┘ │
            └──────────────────────────────┬────────────────────────────────┘
                                           │
            ┌──────────────────────────────▼────────────────────────────────┐
            │                   PostgreSQL 16 + pgvector                    │
            │                                                               │
            │  19 tables (BCNF) . GIN full-text indexes . 1024-dim vectors  │
            │  6 stored procedures . 5 triggers . recursive-CTE BFS        │
            └───────────────────────────────────────────────────────────────┘
```

Three interfaces share the same core engine. No functionality is locked to a single client.

---

## Data Pipeline

Every document goes through five stages before it is queryable:

```
  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
  │   PARSE &    │     │              │     │              │     │   EXTRACT    │     │             │
  │  NORMALIZE   │────>│  DEDUPLICATE │────>│    EMBED     │────>│  (LLM +     │────>│ QUERY-READY │
  │              │     │              │     │              │     │  fallback)   │     │             │
  └─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
        │                    │                    │                     │                    │
  Strip control        SHA-256 hash         Voyage AI            Claude Haiku         4 search modes
  chars, collapse      content-addressed    voyage-3 model       entities, typed      fulltext, semantic
  whitespace,          storage, skip if     1024-dim vectors     relationships,       graph, hybrid
  detect format        seen, version if     upsert on            concepts with        RBAC-filtered
  (PDF/DOCX/URL)       content changed      (type, id, model)    confidence scores    at read time
```

The pipeline is **idempotent**. SHA-256 deduplication and `ON CONFLICT` upserts mean it is safe to re-run at any time. Embedding failures never roll back document writes. LLM extraction failures fall back to keyword matching. Full-text search is always available.

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph
cp .env.example .env          # add your ANTHROPIC_API_KEY and VOYAGE_API_KEY
docker compose up
```

The API is live at `http://localhost:8000` with interactive Swagger docs at `/docs`.

PostgreSQL schema, stored procedures, and seed data initialize automatically on first run.

<details>
<summary><b>Manual setup (without Docker)</b></summary>
<br/>

```bash
# 1. Create and initialize the database
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/procedures_triggers.sql
psql -d omnigraph -f sql/sample_data.sql

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env    # fill in API keys

# 4. Run
uvicorn api.main:app --reload --port 8000    # REST API
python exec.py                                # or terminal UI
```

</details>

---

## Search Strategies

OmniGraph supports four retrieval modes. Hybrid is the production default.

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │                        HYBRID SEARCH                                  │
  │                                                                       │
  │   fulltext (1.0)          semantic (1.2)          graph (0.8)         │
  │   ┌─────────────┐        ┌─────────────┐        ┌─────────────┐      │
  │   │  tsvector    │        │  Voyage AI   │        │  Entity ->  │      │
  │   │  tsquery     │        │  cosine      │        │  Relation ->│      │
  │   │  GIN index   │        │  distance    │        │  Document   │      │
  │   └──────┬──────┘        └──────┬──────┘        └──────┬──────┘      │
  │          │                      │                      │              │
  │          └──────────────────────┼──────────────────────┘              │
  │                                 │                                     │
  │                        weighted rank merge                            │
  │                                 │                                     │
  │                          RBAC post-filter                             │
  │                 (users see only what they can access)                  │
  └────────────────────────────────────────────────────────────────────────┘
```

| Strategy | Mechanism | Best for |
|:---------|:----------|:---------|
| `fulltext` | PostgreSQL `tsvector` / `tsquery` with GIN indexes | Exact keywords, acronyms, IDs |
| `semantic` | Voyage AI `voyage-3` embeddings, pgvector cosine distance | Natural-language questions, synonyms |
| `graph` | Entity-relation-document traversal | "What else connects to X?" |
| `hybrid` | Weighted blend of all three | General-purpose production queries |

Every result is post-filtered through role-based access control. Users only see documents matching their sensitivity clearance.

---

## MCP Server -- Claude Desktop Integration

Add OmniGraph to Claude Desktop and Claude gets direct access to the knowledge graph. No REST calls, no glue code.

`~/.claude/claude_desktop_config.json` (Mac/Linux):

```json
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
```

Restart Claude Desktop. OmniGraph appears in the tools panel. A pre-filled example is in [`claude_desktop_config.example.json`](claude_desktop_config.example.json).

<details>
<summary><b>All 13 MCP tools</b></summary>
<br/>

| Category | Tool | Description |
|:---------|:-----|:------------|
| **Search** | `search` | Hybrid / fulltext / semantic / graph search |
| | `read_document` | Fetch full document text by ID |
| | `find_experts` | Domain experts ranked by concept contribution |
| | `get_entity_documents` | All documents linked to a named entity |
| | `find_related_concepts` | Concept hierarchy and co-occurrence graph |
| **Ingest** | `ingest_document` | Add text to the knowledge graph |
| | `ingest_url` | Fetch a URL and ingest its content |
| **Explore** | `graph_stats` | Live entity / relation / concept counts |
| | `list_entities` | Browse entities with optional type filter |
| | `entity_neighborhood` | N-hop entity graph traversal |
| | `list_documents` | Paginated document listing |
| **Utility** | `extract_entities` | Analyze text without writing to DB |
| | `build_graph` | Backfill extraction on all unprocessed documents |

</details>

<details>
<summary><b>MCP prompt templates</b></summary>
<br/>

These are research workflows available from the Claude Desktop prompt menu:

- **`research_topic`** -- Search documents, read top results, explore related concepts, find experts, synthesize an answer with citations.
- **`analyze_document`** -- Read a document by ID, extract entities, find related documents and domain experts.
- **`explore_entity`** -- Map all connections for a named entity: linked documents, relationships, related concepts.

</details>

---

## REST API

Interactive docs at `/docs` when the server is running. All `/api/v1/*` endpoints require an `X-API-Key` header (set via `OMNIGRAPH_API_KEY` in `.env`; leave empty to disable auth in development).

<details>
<summary><b>All 14 endpoints</b></summary>
<br/>

| Method | Path | Description |
|:-------|:-----|:------------|
| `GET` | `/health` | Database connectivity and capability flags |
| `POST` | `/api/v1/auth/login` | Resolve username to user_id and roles |
| `POST` | `/api/v1/documents/ingest` | Ingest plain text |
| `POST` | `/api/v1/documents/upload` | Upload PDF / DOCX / TXT file |
| `POST` | `/api/v1/documents/ingest-url` | Fetch a URL and ingest its content |
| `GET` | `/api/v1/documents` | Paginated document listing with filters |
| `GET` | `/api/v1/documents/{id}` | Full document detail |
| `DELETE` | `/api/v1/documents/{id}` | Soft-archive a document |
| `POST` | `/api/v1/search` | Search (hybrid / fulltext / semantic / graph) |
| `POST` | `/api/v1/chat` | Conversational RAG agent with citations |
| `GET` | `/api/v1/graph/stats` | Entity, relation, and concept counts |
| `GET` | `/api/v1/graph/entities` | Browse entities with type filter |
| `GET` | `/api/v1/graph/entities/{id}/neighborhood` | N-hop graph traversal |
| `POST` | `/api/v1/graph/build` | Backfill extraction on unprocessed documents |

</details>

```bash
# Upload a PDF -- text extracted, entities extracted by Claude, embeddings stored
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@paper.pdf" -F "uploaded_by=1" -F "source_type=research_paper"

# Hybrid search across all four strategies
curl -X POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"query": "federated learning privacy", "strategy": "hybrid", "user_id": 1}'

# Ask the RAG agent -- returns an answer with [doc_id=X] citations
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"message": "Who are the experts on Kubernetes?", "user_id": 1}'
```

---

## Database Schema

19 tables normalized to BCNF, organized in five layers:

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │  IDENTITY & ACCESS                                                  │
  │  roles . users . user_roles . access_policies                       │
  ├─────────────────────────────────────────────────────────────────────┤
  │  CONTENT                                                            │
  │  documents . document_versions . taxonomy . tags . document_tags    │
  ├─────────────────────────────────────────────────────────────────────┤
  │  KNOWLEDGE GRAPH                                                    │
  │  entities . relations . concepts . concept_hierarchy                │
  │  entity_concepts . document_entities . document_concepts            │
  ├─────────────────────────────────────────────────────────────────────┤
  │  SEMANTIC LAYER                                                     │
  │  embeddings  (polymorphic: documents, entities, and concepts)       │
  ├─────────────────────────────────────────────────────────────────────┤
  │  OBSERVABILITY                                                      │
  │  query_logs . audit_logs                                            │
  └─────────────────────────────────────────────────────────────────────┘
```

<div align="center">
<img src="./database-schema.jpeg" alt="OmniGraph ER diagram" width="860"/>
</div>

<br/>

**Key design decisions:**

| Decision | Rationale |
|:---------|:----------|
| Polymorphic embeddings table | Single `embeddings` table covers documents, entities, and concepts via `(source_type, source_id)`. Uniform semantic search across all node types. |
| Directed relations with provenance | Every `relations` row stores `source_document_id`. Every graph edge is auditable back to the document that created it. |
| Row-level sensitivity enforcement | `sensitivity_level` is re-checked at read time by `AccessControlManager`, not just at write time. Four tiers: public, internal, confidential, restricted. |
| Shortest-path BFS in SQL | `sp_shortest_path()` is a recursive-CTE PostgreSQL function. No application-side graph library required. |
| SHA-256 content deduplication | Hash computed on write; duplicate detection is a single indexed lookup. Re-ingesting the same content is a no-op. |

---

## Project Structure

```
Omni-Graph/
│
├── mcp_server/
│   └── server.py                       MCP server (13 tools, 3 resources, 3 prompts)
│
├── api/
│   ├── main.py                         FastAPI application (14 REST endpoints)
│   ├── file_parser.py                  PDF / DOCX / URL content extraction
│   ├── models.py                       Pydantic request and response schemas
│   ├── auth.py                         API-key authentication middleware
│   └── dependencies.py                 Database connection dependency injection
│
├── omnigraph/
│   ├── ingestion_pipeline.py           Normalize, deduplicate, version, embed
│   ├── entity_relation_extractor.py    Claude NLP extraction + keyword fallback
│   ├── graph_builder.py                Entity/relation CRUD and auto-backfill
│   ├── semantic_query_engine.py        Fulltext, vector, graph, hybrid search
│   ├── access_control_audit.py         RBAC, sensitivity tiers, audit logging
│   ├── agentic_rag.py                  Claude tool-use agent loop
│   ├── embedder.py                     Voyage AI embedding wrapper
│   └── console_app.py                  Interactive terminal UI
│
├── sql/
│   ├── schema.sql                      19 tables, constraints, 25+ indexes
│   ├── procedures_triggers.sql         6 stored procedures, 5 triggers
│   ├── sample_data.sql                 Seed users, roles, and documents
│   └── retrieval.sql                   Advanced query examples
│
├── docker-compose.yml                  PostgreSQL (pgvector) + API server
├── Dockerfile                          Python 3.11-slim, uvicorn with 2 workers
├── requirements.txt
├── .env.example
└── claude_desktop_config.example.json
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values.

| Variable | Default | Required | Purpose |
|:---------|:--------|:---------|:--------|
| `ANTHROPIC_API_KEY` | -- | Yes | Claude agent and LLM-powered entity extraction |
| `VOYAGE_API_KEY` | -- | Yes | Voyage AI embeddings for semantic search |
| `OMNIGRAPH_API_KEY` | *(empty)* | No | REST API authentication (empty = open in dev) |
| `OMNIGRAPH_DB_HOST` | `localhost` | No | Database host (use container name in Docker) |
| `OMNIGRAPH_DB_PORT` | `5432` | No | Database port |
| `OMNIGRAPH_DB_NAME` | `omnigraph` | No | Database name |
| `OMNIGRAPH_DB_USER` | `postgres` | No | Database user |
| `OMNIGRAPH_DB_PASSWORD` | `postgres` | No | Database password |
| `OMNIGRAPH_DEFAULT_USER_ID` | `1` | No | Default RBAC user for MCP server |

---

## Contributing

Contributions are welcome.

1. Fork the repo and create a branch from `main` (`feat/...`, `fix/...`, `docs/...`)
2. Set up your local environment using the quick start above
3. Make your changes -- keep PRs focused on a single concern
4. Open a pull request with a description of what you changed and why

**Where to start:**

| If you want to... | Look at |
|:-------------------|:--------|
| Add an MCP tool | `mcp_server/server.py` -- add to `list_tools()` and `call_tool()` |
| Add a REST endpoint | `api/main.py` + add a Pydantic model in `api/models.py` |
| Support a new file format | `api/file_parser.py` -- add a `parse_xyz()` function and wire it into `parse_file()` |
| Change entity extraction | `omnigraph/entity_relation_extractor.py` -- modify `_LLM_EXTRACTION_PROMPT` or `_extract_keywords()` |
| Add a search strategy | `omnigraph/semantic_query_engine.py` -- add a `_search_*()` method and wire it into `search()` |

**Good first issues:** additional file formats (PPTX, CSV, Markdown), test coverage, new MCP tools, streaming chat responses, a frontend UI.

---

## Tech Stack

<div align="center">

![Python](https://img.shields.io/badge/Python_3.11-14191f?style=for-the-badge&logo=python&logoColor=3776AB)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-14191f?style=for-the-badge&logo=postgresql&logoColor=4169E1)
![pgvector](https://img.shields.io/badge/pgvector-14191f?style=for-the-badge&logo=postgresql&logoColor=6366F1)
![FastAPI](https://img.shields.io/badge/FastAPI-14191f?style=for-the-badge&logo=fastapi&logoColor=009688)
![Docker](https://img.shields.io/badge/Docker-14191f?style=for-the-badge&logo=docker&logoColor=2496ED)
![Anthropic](https://img.shields.io/badge/Claude_AI-14191f?style=for-the-badge&logo=anthropic&logoColor=D4A574)
![Voyage AI](https://img.shields.io/badge/Voyage_AI-14191f?style=for-the-badge&logo=voyager&logoColor=A78BFA)
![MCP](https://img.shields.io/badge/Model_Context_Protocol-14191f?style=for-the-badge&logo=anthropic&logoColor=8B5CF6)

</div>

| Layer | Technology |
|:------|:-----------|
| Language | Python 3.11+ |
| Database | PostgreSQL 16, pgvector extension |
| Embeddings | Voyage AI `voyage-3` (1024-dimensional, cosine distance) |
| LLM | Anthropic Claude -- Haiku for extraction, Opus for the RAG agent |
| REST API | FastAPI, Uvicorn (2 workers) |
| File parsing | pdfminer.six, python-docx, httpx + BeautifulSoup4 |
| AI integration | Model Context Protocol SDK (`mcp >= 1.0`) |
| Deployment | Docker Compose (pgvector/pgvector:pg16 + Python 3.11-slim) |

---

## License

MIT -- see [LICENSE](LICENSE).

---

<div align="center">

**[Star this repo](https://github.com/vaishcodescape/Omni-Graph)** if you find it useful.

Built with [Anthropic Claude](https://anthropic.com) and [pgvector](https://github.com/pgvector/pgvector) and [FastAPI](https://fastapi.tiangolo.com) and [Model Context Protocol](https://modelcontextprotocol.io)

</div>
