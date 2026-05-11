<div align="center">

# OmniGraph

### Enterprise Knowledge Graph & Agentic RAG System — Fully Automated & API-First

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D4A574?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST_API-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MCP](https://img.shields.io/badge/MCP-Server-8B5CF6?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**Ingest documents. Extract knowledge graphs. Query with AI agents.**

OmniGraph ingests documents from text, files (PDF / DOCX), or URLs; extracts entities, concepts, and relationships using **Claude-powered NLP**; stores everything in a queryable graph; and exposes retrieval through a hybrid search engine (full-text + vector + graph traversal) fronted by an Anthropic tool-use agent.

Deploy in one command with Docker. Integrate with any client via the REST API. Or run the interactive terminal UI locally.

<br/>

<img src="./database-schema.jpeg" alt="OmniGraph database schema ER diagram" width="800" />

</div>

---

## What's New

- **MCP Server** — Native Model Context Protocol server: plug OmniGraph directly into Claude Desktop as 13 tools, 3 resources, and 3 reusable prompts — no REST calls needed
- **REST API** — Full FastAPI layer covering document ingest, search, Claude agent chat, and graph management
- **File ingestion** — Upload PDF, DOCX, or TXT files; fetch and ingest any public URL automatically
- **Claude-powered NLP** — Entity/concept/relationship extraction upgraded from static keyword lists to `claude-haiku-4-5` LLM extraction (keywords merged as fallback)
- **Docker** — One-command deployment: `docker compose up` — pgvector + API, schema auto-initialized
- **Auto graph building** — Every ingested document triggers entity extraction; `POST /api/v1/graph/build` backfills any gaps

---

## Highlights

- **Hybrid retrieval engine** — Postgres full-text (`tsvector` + GIN), 1024-dim Voyage AI vector similarity, and graph traversal — unified behind a single weighted ranker
- **Agentic RAG** — Anthropic Claude agent with a native tool-use loop exposing five RBAC-gated retrieval tools (`hybrid_search`, `find_experts`, `get_entity_documents`, `find_related_concepts`, `get_document_content`)
- **Relational knowledge graph** — 19-table PostgreSQL schema: documents, entities, concepts, relations, taxonomies, user/role access policies
- **Deterministic ingestion** — Text normalization → SHA-256 deduplication → versioned writes → embedding via UPSERT on `(source_type, source_id, model_name)`
- **Enterprise security** — Row-level sensitivity (`public / internal / confidential / restricted`), RBAC enforced at read time, full audit trail
- **Database-first design** — 6 stored procedures and 5 triggers enforce invariants in SQL; shortest-path BFS implemented as a recursive-CTE PostgreSQL function

---

## Tech Stack

<table>
<tr>
<td align="center" width="96">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="48" height="48" alt="Python" />
<br/><b>Python</b>
</td>
<td align="center" width="96">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="48" height="48" alt="PostgreSQL" />
<br/><b>PostgreSQL</b>
</td>
<td align="center" width="96">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/sqlalchemy/white" />
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/sqlalchemy/sqlalchemy-original.svg" width="48" height="48" alt="pgvector" />
</picture>
<br/><b>pgvector</b>
</td>
<td align="center" width="96">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/anthropic/white" />
<img src="https://upload.wikimedia.org/wikipedia/commons/7/78/Anthropic_logo.svg" width="48" height="48" alt="Anthropic" />
</picture>
<br/><b>Claude AI</b>
</td>
</tr>
</table>

| Layer | Technology | Purpose |
|:---|:---|:---|
| **Language** | Python 3.11+ | Core application logic |
| **REST API** | FastAPI + Uvicorn | HTTP layer, file upload, SSE |
| **Database** | PostgreSQL 16+ | Relational storage, FTS (`tsvector` + GIN indexes) |
| **Vector Store** | pgvector (1024-dim, cosine) | Semantic similarity search |
| **Embeddings** | Voyage AI (`voyage-3`) | Document & entity embedding generation |
| **LLM Agent** | Anthropic Claude (tool-use + streaming) | Agentic RAG with 5 retrieval tools |
| **NLP Extraction** | `claude-haiku-4-5` + keyword fallback | Entity, concept, relationship extraction |
| **File Parsing** | pdfminer.six · python-docx · httpx + BeautifulSoup4 | PDF / DOCX / URL text extraction |
| **MCP Server** | Model Context Protocol (mcp SDK) | Native Claude Desktop integration |
| **Deployment** | Docker + docker-compose | One-command full-stack deployment |
| **Terminal UI** | ANSI console | Interactive TUI (still available) |

---

## Architecture

```text
 ┌─────────────────────────────────────────────────────────────────┐
 │                  Clients (API / Browser / CLI)                  │
 └─────────────────────────────┬───────────────────────────────────┘
                               │
 ┌─────────────────────────────▼───────────────────────────────────┐
 │                     FastAPI REST API  :8000                     │
 │  /ingest  /upload  /ingest-url  /search  /chat  /graph/*        │
 │                  X-API-Key authentication                       │
 └───┬──────────────┬─────────────────────────────┬───────────────┘
     │              │                             │
     ▼              ▼                             ▼
┌─────────┐  ┌────────────┐              ┌─────────────────┐
│Ingestion│  │ Agentic RAG│              │  Graph / Search │
│Pipeline │  │(Claude agent│             │     Engine      │
└────┬────┘  └─────┬──────┘             └────────┬────────┘
     │             │                             │
     ▼             ▼                             ▼
┌───────────────────────────────────────────────────────────┐
│            Claude-Powered Entity Extractor                │
│   claude-haiku-4-5  +  keyword/regex fallback             │
└───────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────┐
│                PostgreSQL  —  schema: omnigraph            │
│  documents · entities · concepts · relations · embeddings  │
│  roles · access_policies · audit_logs · query_logs         │
└───────────────────────────────────────────────────────────┘
```

---

## Data Flow

```text
Input (text / PDF / DOCX / URL)
  → parse & normalize (strip control chars, collapse whitespace)
  → SHA-256 content hash → dedupe probe
      ├─ hit  → insert new row in document_versions
      └─ miss → INSERT into documents
              → Voyage AI embed → upsert into embeddings (pgvector)
              → Claude Haiku NLP extraction:
                  ├─ entities       → entities + document_entities
                  ├─ concepts       → concepts + document_concepts
                  └─ relationships  → relations (entity → entity edges)
                  (keyword/regex layer merges in any missed known terms)
```

All stages are idempotent: hash-based dedup, `ON CONFLICT` upserts on graph edges, stable embedding keys `(source_type, source_id, model_name)`.

---

## Quick Start — Docker (recommended)

```bash
# 1. Clone and configure
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and VOYAGE_API_KEY

# 2. Start everything (postgres + API)
docker compose up

# API is live at   http://localhost:8000
# Swagger docs at  http://localhost:8000/docs
```

PostgreSQL schema, stored procedures, and sample data are initialized automatically on first startup.

---

## Quick Start — Local

```bash
# 1. Create and seed the database
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/sample_data.sql
psql -d omnigraph -f sql/procedures_triggers.sql

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env    # fill in your values

# 4a. Start the REST API
uvicorn api.main:app --reload --port 8000

# 4b. Or use the terminal UI
python exec.py
```

---

## MCP Server — Claude Desktop Integration

OmniGraph ships as a first-class **Model Context Protocol server**. Add it to Claude Desktop and Claude can directly search the knowledge graph, ingest documents, explore the entity graph, and run research workflows — without any manual API calls.

### Setup (Claude Desktop)

1. Copy `claude_desktop_config.example.json` into your Claude Desktop config:
   - **Mac / Linux:** `~/.claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

2. Update the `cwd` field to your absolute path and fill in your API keys.

3. Restart Claude Desktop — OmniGraph will appear in the tools panel.

```json
{
  "mcpServers": {
    "omnigraph": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/Omni-Graph",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "VOYAGE_API_KEY": "pa-...",
        "OMNIGRAPH_DB_HOST": "localhost",
        "OMNIGRAPH_DB_USER": "postgres",
        "OMNIGRAPH_DB_PASSWORD": "postgres"
      }
    }
  }
}
```

### MCP Tools (13)

| Tool | Description |
|------|-------------|
| `search` | Hybrid / fulltext / semantic / graph search across all documents |
| `read_document` | Fetch full document content by ID |
| `find_experts` | Domain experts ranked by concept contribution |
| `get_entity_documents` | Documents linked to a named entity |
| `find_related_concepts` | Concept hierarchy + co-occurrence |
| `ingest_document` | Ingest text into the knowledge graph |
| `ingest_url` | Fetch a URL and ingest its content |
| `graph_stats` | Entity / relation / concept / document counts |
| `list_entities` | Browse entities with optional type filter |
| `entity_neighborhood` | N-hop entity graph traversal |
| `list_documents` | Paginated document listing |
| `extract_entities` | Run Claude NLP extraction on arbitrary text (no DB write) |
| `build_graph` | Backfill extraction for all unprocessed documents |

### MCP Resources (3)

| URI | Description |
|-----|-------------|
| `omnigraph://graph/stats` | Live knowledge graph statistics |
| `omnigraph://documents/recent` | 20 most recently ingested documents |
| `omnigraph://entities/top` | 50 highest-confidence entities |

### MCP Prompts (3)

| Prompt | Arguments | What it does |
|--------|-----------|--------------|
| `research_topic` | `topic`, `depth` | Deep-research any topic: search → read → concepts → experts → synthesize |
| `analyze_document` | `document_id` | Full document analysis: content → entities → related docs → experts |
| `explore_entity` | `entity_name` | Map all entity connections: neighborhood → documents → concepts |

### Run standalone (debug)

```bash
python -m mcp_server.server
```

---

## REST API Reference

All `/api/v1/*` endpoints require an `X-API-Key` header matching `OMNIGRAPH_API_KEY`.
Leave that env var empty to disable auth in development.

Interactive docs always available at [`/docs`](http://localhost:8000/docs).

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | DB ping, capability flags (LLM, semantic search) |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Resolve username → `user_id` + roles |

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "chen.wei"}'
# → {"user_id": 2, "username": "chen.wei", "roles": ["analyst"]}
```

### Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/ingest` | Ingest plain text |
| `POST` | `/api/v1/documents/upload` | Upload PDF / DOCX / TXT |
| `POST` | `/api/v1/documents/ingest-url` | Fetch a URL and ingest its text |
| `GET` | `/api/v1/documents` | Paginated list (filterable by type / sensitivity) |
| `GET` | `/api/v1/documents/{id}` | Full detail including content |
| `DELETE` | `/api/v1/documents/{id}` | Soft-archive |

```bash
# Upload a PDF — text extracted automatically
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@report.pdf" -F "uploaded_by=1" -F "source_type=report"

# Ingest a URL
curl -X POST http://localhost:8000/api/v1/documents/ingest-url \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/article","uploaded_by":1}'
```

All ingest endpoints accept `"auto_extract": true` (default) — Claude NLP extraction runs immediately after ingest.

### Search

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/search` | Hybrid / fulltext / semantic / graph search |

```json
POST /api/v1/search
{"query": "Kubernetes container orchestration", "strategy": "hybrid", "limit": 10, "user_id": 1}
```

### Chat (Agentic RAG)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/chat` | Ask the Claude agent; returns answer + citations + tools used |

```json
POST /api/v1/chat
{"message": "Who are the experts on federated learning?", "user_id": 1}
```

### Graph

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/graph/stats` | Total entities, relations, concepts, documents |
| `GET` | `/api/v1/graph/entities` | Paginated entity list with optional type filter |
| `GET` | `/api/v1/graph/entities/{id}/neighborhood` | N-hop neighborhood (depth 1–4) |
| `POST` | `/api/v1/graph/build` | Backfill extraction for all unprocessed documents |

---

## Retrieval Strategies

| Strategy | Mechanism | Best for |
|---|---|---|
| `fulltext` | PostgreSQL `tsvector` / `tsquery`, GIN-indexed | Exact keywords, acronyms |
| `semantic` | Voyage `voyage-3` → pgvector nearest neighbor | Natural-language questions, paraphrases |
| `graph` | Entity → relation → entity → document traversal | "What else is connected to X?" |
| `hybrid` (default) | All three, blended `{fulltext: 1.0, semantic: 1.2, graph: 0.8}` | Most production queries |

Every result is post-filtered through RBAC — users only see documents they have `read` access to.

---

## Core Modules

| Module | Responsibility |
|---|---|
| [`api/main.py`](api/main.py) | FastAPI app — all 13 REST endpoints |
| [`api/file_parser.py`](api/file_parser.py) | PDF, DOCX, and URL text extraction |
| [`api/auth.py`](api/auth.py) | X-API-Key middleware |
| [`omnigraph/ingestion_pipeline.py`](omnigraph/ingestion_pipeline.py) | Normalization, SHA-256 dedup, versioning, batch ingest, embedding |
| [`omnigraph/entity_relation_extractor.py`](omnigraph/entity_relation_extractor.py) | Claude Haiku LLM extraction + keyword/regex fallback; entity/concept/relation storage |
| [`omnigraph/graph_builder.py`](omnigraph/graph_builder.py) | Entity/relation CRUD, taxonomy, concept hierarchies, neighborhood traversal, auto-backfill |
| [`omnigraph/semantic_query_engine.py`](omnigraph/semantic_query_engine.py) | Fulltext, vector, graph, and hybrid search with weighted ranking |
| [`omnigraph/access_control_audit.py`](omnigraph/access_control_audit.py) | RBAC enforcement, sensitivity checks, query + audit logging |
| [`omnigraph/agentic_rag.py`](omnigraph/agentic_rag.py) | Anthropic tool-use agent with 5 RBAC-gated retrieval tools |
| [`omnigraph/embedder.py`](omnigraph/embedder.py) | Voyage AI client wrapper with graceful degradation |
| [`omnigraph/console_app.py`](omnigraph/console_app.py) | ANSI terminal UI (search, agent, graph exploration) |

---

## Database Schema — 19 Tables

All objects live in the `omnigraph` schema. Full DDL in [`sql/schema.sql`](sql/schema.sql).

**Identity & Access**: `roles` · `users` · `user_roles` · `access_policies`
**Content**: `documents` · `document_versions` · `taxonomy` · `tags` · `document_tags`
**Knowledge Graph**: `entities` · `relations` · `concepts` · `concept_hierarchy` · `entity_concepts` · `document_entities` · `document_concepts`
**Semantic Layer**: `embeddings` (polymorphic on `source_type + source_id`, pgvector)
**Observability**: `query_logs` · `audit_logs`

Key design decisions:

- **Polymorphic embeddings** — One `embeddings` table spans documents, entities, and concepts; enables semantic search across all graph node types uniformly.
- **Directed relations** — `relations(source_entity_id, target_entity_id, relation_type, strength, source_document_id)` preserves provenance back to the originating document.
- **Row-level sensitivity** — `documents.sensitivity_level` is the final authority; every retrieval is re-checked at read time.
- **Shortest-path BFS** — `sp_shortest_path(source_id, target_id)` implemented as a recursive-CTE PostgreSQL function.

---

## Programmatic Usage

```python
from omnigraph import DatabaseConnection, DocumentIngester, SemanticQueryEngine
from omnigraph import EntityRelationExtractor, get_anthropic_agent

db = DatabaseConnection()   # reads all params from env vars
db.connect()

# Ingest text — deduplicates, embeds, auto-extracts entities
ingester = DocumentIngester(db)
doc_id = ingester.ingest_document(
    title="Container Orchestration Primer",
    source_type="technical_doc",
    content="Kubernetes orchestrates Docker containers across clusters...",
    uploaded_by=1,
    sensitivity_level="internal",
)

# Extract entities with Claude Haiku (keyword fallback if no API key)
extractor = EntityRelationExtractor(db)
result = extractor.process_document(doc_id)
print(result["entities"])      # [{name, entity_type, confidence, ...}]
print(result["relationships"]) # [{source, target, relation_type, strength}]

# Hybrid search, RBAC-filtered
engine = SemanticQueryEngine(db, user_id=1)
hits = engine.search("container orchestration", strategy="hybrid", limit=5)

# Ask the Claude agent
agent = get_anthropic_agent(db, user_id=1)
answer = agent.run("Who are the experts on Kubernetes?")
print(answer["answer"])
print(answer["citations"])
```

---

## Configuration Reference

| Env var | Default | Purpose |
|---|---|---|
| `OMNIGRAPH_DB_HOST` | `localhost` | PostgreSQL host |
| `OMNIGRAPH_DB_PORT` | `5432` | PostgreSQL port |
| `OMNIGRAPH_DB_NAME` | `omnigraph` | Database name |
| `OMNIGRAPH_DB_USER` | `postgres` | PostgreSQL user |
| `OMNIGRAPH_DB_PASSWORD` | `postgres` | PostgreSQL password |
| `ANTHROPIC_API_KEY` | — | Required for Claude agent + LLM entity extraction |
| `VOYAGE_API_KEY` | — | Required for semantic / vector search |
| `OMNIGRAPH_API_KEY` | `""` (open) | API key for `X-API-Key` header; leave empty to disable auth |

Copy `.env.example` to `.env` and fill in your values.

---

## Repository Layout

```text
Omni-Graph/
├── exec.py                          # Terminal UI entrypoint
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── database-schema.jpeg
├── mcp_server/                      # MCP Server (Claude Desktop)
│   └── server.py                    # 13 tools, 3 resources, 3 prompts
├── claude_desktop_config.example.json
├── api/                             # REST API layer
│   ├── main.py                      # FastAPI app + all routes
│   ├── models.py                    # Pydantic request/response schemas
│   ├── auth.py                      # X-API-Key middleware
│   ├── dependencies.py              # DB dependency injection
│   └── file_parser.py               # PDF / DOCX / URL text extraction
├── omnigraph/                       # Core library
│   ├── ingestion_pipeline.py        # Ingest, dedup, versioning, embedding
│   ├── entity_relation_extractor.py # Claude NLP + keyword extraction
│   ├── graph_builder.py             # Entity/relation CRUD + auto-backfill
│   ├── semantic_query_engine.py     # Fulltext / vector / graph / hybrid search
│   ├── access_control_audit.py      # RBAC, audit logging
│   ├── agentic_rag.py               # Claude tool-use agent
│   ├── embedder.py                  # Voyage AI wrapper
│   └── console_app.py               # Terminal UI
└── sql/
    ├── schema.sql                   # 19 tables, constraints, indexes
    ├── sample_data.sql              # Seed roles / users / documents
    ├── procedures_triggers.sql      # 6 stored procedures + 5 triggers
    ├── retrieval.sql                # Advanced retrieval queries
    └── queries.sql                  # CTE / window function examples
```

---

## Engineering Practices

- **LLM-first, keyword fallback** — Claude extraction handles any entity; keyword lists ensure well-known tech terms are never missed.
- **Separation of concerns** — Retrieval, access control, and orchestration are distinct modules; the agent composes them.
- **SQL-as-contract** — FTS maintenance, audit emission, and taxonomy invariants are enforced by triggers and stored procedures.
- **Idempotent writes** — Hash dedup, `ON CONFLICT` upserts, and stable embedding keys make the pipeline safe to re-run.
- **Graceful degradation** — Embedding failures don't roll back document writes; LLM failures fall back to keyword extraction; FTS always works.
- **Provenance** — Every extracted relation stores `source_document_id`; every query is logged to `query_logs`.

---

## Sample Seed Users

Seeded by `sample_data.sql`: `agarwal.priya` · `chen.wei` · `johnson.mark` · `martinez.sofia` · `okafor.emeka` · `tanaka.yuki` · `williams.alex` · `kumar.rahul` · `fischer.anna` · `brown.david`

---

## Notes

- SQL initialization order: `schema.sql` → `sample_data.sql` → `procedures_triggers.sql`. Docker handles this automatically.
- To grant `view_graph` to the admin role:

```sql
UPDATE omnigraph.roles
SET permissions = array_append(permissions, 'view_graph')
WHERE role_name = 'admin'
  AND NOT ('view_graph' = ANY(permissions));
```

---

## License

MIT — see [LICENSE](LICENSE).
