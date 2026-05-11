<div align="center">

# OmniGraph

**An enterprise-grade knowledge graph and agentic RAG platform — fully automated and API-first.**

OmniGraph ingests documents from text, files (PDF / DOCX), or URLs; extracts entities, concepts, and relationships using **Claude-powered NLP**; stores everything in a queryable graph; and exposes retrieval through a hybrid search engine (full-text + vector + graph traversal) fronted by an Anthropic tool-use agent.

Deploy in one command with Docker. Integrate with any client via the REST API. Or run the interactive terminal UI locally.

---

## What's New

- **REST API** — Full FastAPI layer covering ingest, search, chat, and graph management
- **File ingestion** — Upload PDF, DOCX, or TXT files directly; fetch and ingest any public URL
- **Claude-powered NLP** — Entity and relationship extraction upgraded from keyword lists to `claude-haiku-4-5` LLM extraction (keywords used as merge + fallback)
- **Docker** — One-command deployment: `docker compose up` — pgvector + API, schema auto-initialized
- **Auto graph building** — Every ingested document is automatically entity-extracted; `POST /api/v1/graph/build` backfills any gaps

**Ingest documents. Extract knowledge graphs. Query with AI agents.**

OmniGraph ingests organizational documents, extracts entities, concepts, and relationships into a queryable graph, and exposes retrieval through a hybrid search engine (full-text + vector + graph traversal) fronted by an Anthropic tool-use agent. Built around production concerns: RBAC, sensitivity tiers, audit trails, versioning, and deterministic deduplication.

<br/>

- **Hybrid retrieval engine** — Postgres full-text (`tsvector` + GIN), 1024-dim Voyage AI vector similarity, and graph traversal — unified behind a single weighted ranker
- **Agentic RAG** — Anthropic Claude agent with a native tool-use loop exposing five RBAC-gated retrieval tools (`hybrid_search`, `find_experts`, `get_entity_documents`, `find_related_concepts`, `get_document_content`)
- **Relational knowledge graph** — 19-table PostgreSQL schema: documents, entities, concepts, relations, taxonomies, user/role access policies
- **Deterministic ingestion** — Text normalization → SHA-256 deduplication → versioned writes → embedding via UPSERT on `(source_type, source_id, model_name)`
- **Enterprise security** — Row-level sensitivity (`public / internal / confidential / restricted`), RBAC enforced at read time, full audit trail
- **Database-first design** — 6 stored procedures and 5 triggers enforce invariants in SQL; shortest-path BFS implemented as a recursive-CTE PostgreSQL function

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| REST API | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector |
| Vector store | pgvector (1024-dim, cosine) |
| Embeddings | Voyage AI — `voyage-3` |
| LLM Agent | Anthropic Claude (tool-use + streaming) |
| NLP Extraction | `claude-haiku-4-5` (LLM-first, keyword fallback) |
| File parsing | pdfminer.six · python-docx · httpx + BeautifulSoup4 |
| Driver | psycopg2 |
| Deployment | Docker + docker-compose |
| Terminal UI | ANSI console (still available) |

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
git clone https://github.com/your-org/Omni-Graph.git
cd Omni-Graph
cp .env.example .env
# Edit .env — fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY

# 2. Start everything (postgres + API)
docker compose up

# API is live at http://localhost:8000
# Interactive docs at http://localhost:8000/docs
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

# 3. Configure credentials
cp .env.example .env   # then fill in your values
source .env            # or use python-dotenv (loaded automatically)

# 4a. Start the REST API
uvicorn api.main:app --reload --port 8000

# 4b. Or launch the terminal UI
python exec.py
```

---

## REST API Reference

All `/api/v1/*` endpoints require an `X-API-Key` header matching `OMNIGRAPH_API_KEY`. Leave that env var empty to disable auth in development.

Interactive docs are always available at [`/docs`](http://localhost:8000/docs).

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Database ping, capability flags (LLM extraction, semantic search) |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Look up username → returns `user_id`, roles |

```json
POST /api/v1/auth/login
{ "username": "chen.wei" }

→ { "user_id": 2, "username": "chen.wei", "full_name": "Wei Chen", "roles": ["analyst"] }
```

### Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/ingest` | Ingest a plain-text document |
| `POST` | `/api/v1/documents/upload` | Upload a file (PDF / DOCX / TXT) |
| `POST` | `/api/v1/documents/ingest-url` | Fetch a URL and ingest its content |
| `GET` | `/api/v1/documents` | Paginated document list (filterable by `source_type`, `sensitivity_level`) |
| `GET` | `/api/v1/documents/{id}` | Full document detail including content |
| `DELETE` | `/api/v1/documents/{id}` | Soft-archive (content preserved for audit) |

```bash
# Ingest a text document
curl -X POST http://localhost:8000/api/v1/documents/ingest \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"title":"My Report","content":"...","source_type":"report","uploaded_by":1}'

# Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@report.pdf" -F "uploaded_by=1" -F "source_type=report"

# Ingest a URL
curl -X POST http://localhost:8000/api/v1/documents/ingest-url \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/article","uploaded_by":1}'
```

All ingest endpoints accept `"auto_extract": true` (default) to immediately run Claude NLP extraction and store entities/concepts/relationships.

### Search

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/search` | Hybrid / fulltext / semantic / graph search |

```json
POST /api/v1/search
{
  "query": "Kubernetes container orchestration",
  "strategy": "hybrid",
  "limit": 10,
  "user_id": 1
}
```

Strategies: `hybrid` (default) · `fulltext` · `semantic` · `graph`

Results are post-filtered through RBAC — the requesting user only sees documents they have `read` access to.

### Chat (Agentic RAG)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/chat` | Natural-language Q&A with Claude agent, returns answer + citations |

```json
POST /api/v1/chat
{ "message": "Who are the experts on federated learning?", "user_id": 1 }

→ {
    "answer": "Based on the knowledge graph, the top experts on federated learning are...",
    "citations": [{"document_id": 12, "title": "..."}],
    "tools_used": [{"name": "hybrid_search", ...}, {"name": "find_experts", ...}]
  }
```

Requires `ANTHROPIC_API_KEY`. The agent runs a multi-step tool-use loop: search → read → cite.

### Graph

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/graph/stats` | Total entities, relations, concepts, documents |
| `GET` | `/api/v1/graph/entities` | Paginated entity list with optional `entity_type` filter |
| `GET` | `/api/v1/graph/entities/{id}/neighborhood` | N-hop entity neighborhood (max_depth 1–4) |
| `POST` | `/api/v1/graph/build` | Backfill extraction for all unprocessed documents |

---

## Retrieval Strategies

| Strategy | Mechanism | Best for |
|---|---|---|
| `fulltext` | PostgreSQL `tsvector` / `tsquery`, GIN-indexed | Exact keyword matches, acronyms |
| `semantic` | Voyage `voyage-3` → pgvector nearest neighbor | Natural-language questions, paraphrases |
| `graph` | `document_entities → entities → relations → entities → documents` | "What else is connected to X?" |
| `hybrid` (default) | All three, blended `{fulltext: 1.0, semantic: 1.2, graph: 0.8}` | Most production queries |

---

## Core Modules

| Module | Responsibility |
|---|---|
| [`api/main.py`](api/main.py) | FastAPI app with all REST endpoints |
| [`api/file_parser.py`](api/file_parser.py) | PDF, DOCX, and URL text extraction |
| [`api/auth.py`](api/auth.py) | API-key middleware |
| [`omnigraph/ingestion_pipeline.py`](omnigraph/ingestion_pipeline.py) | Normalization, SHA-256 dedup, versioning, batch ingest, embedding |
| [`omnigraph/entity_relation_extractor.py`](omnigraph/entity_relation_extractor.py) | Claude Haiku LLM extraction + keyword/regex fallback; entity, concept, and relationship storage |
| [`omnigraph/graph_builder.py`](omnigraph/graph_builder.py) | Entity/relation CRUD, taxonomy, concept hierarchies, neighborhood traversal, auto-backfill |
| [`omnigraph/semantic_query_engine.py`](omnigraph/semantic_query_engine.py) | Full-text, vector, graph, and hybrid search with weighted ranking |
| [`omnigraph/access_control_audit.py`](omnigraph/access_control_audit.py) | RBAC enforcement, sensitivity checks, query + audit logging |
| [`omnigraph/agentic_rag.py`](omnigraph/agentic_rag.py) | Anthropic tool-use agent with 5 RBAC-gated retrieval tools |
| [`omnigraph/embedder.py`](omnigraph/embedder.py) | Voyage AI client wrapper with graceful degradation |
| [`omnigraph/console_app.py`](omnigraph/console_app.py) | ANSI terminal UI (search, agent, graph exploration) |

---

## Database Schema — 19 Tables

All objects live in the `omnigraph` schema. Full DDL in [`sql/schema.sql`](sql/schema.sql).

<p align="center">
  <img src="./database-schema.jpeg" alt="OmniGraph database schema ER diagram" width="920"/>
</p>

**Identity & Access**: `roles` · `users` · `user_roles` · `access_policies`
**Content**: `documents` · `document_versions` · `taxonomy` · `tags` · `document_tags`
**Knowledge Graph**: `entities` · `relations` · `concepts` · `concept_hierarchy` · `entity_concepts` · `document_entities` · `document_concepts`
**Semantic Layer**: `embeddings` (polymorphic on `source_type + source_id`, pgvector)
**Observability**: `query_logs` · `audit_logs`

Key design decisions:

- **Polymorphic embeddings** — One `embeddings` table spans documents, entities, and concepts; enables semantic search across all graph node types uniformly.
- **Directed relations** — `relations(source_entity_id, target_entity_id, relation_type, strength, source_document_id)` preserves provenance back to the originating document.
- **Row-level sensitivity** — `documents.sensitivity_level` is the final authority; every retrieval is re-checked at read time, not only at write time.
- **Shortest-path BFS** — `sp_shortest_path(source_id, target_id)` implemented as a recursive-CTE PostgreSQL function; used by the graph explorer.

---

## Programmatic Usage (Python SDK)

```python
from omnigraph import DatabaseConnection, DocumentIngester, SemanticQueryEngine
from omnigraph import EntityRelationExtractor, get_anthropic_agent

db = DatabaseConnection()   # reads all params from env vars
db.connect()

# Ingest text — deduplicates, embeds, extracts entities automatically
ingester = DocumentIngester(db)
doc_id = ingester.ingest_document(
    title="Container Orchestration Primer",
    source_type="technical_doc",
    content="Kubernetes orchestrates Docker containers across clusters...",
    uploaded_by=1,
    sensitivity_level="internal",
)

# Extract entities with Claude Haiku (or keyword fallback)
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
| `VOYAGE_API_KEY` | — | Required for semantic/vector search |
| `OMNIGRAPH_API_KEY` | `""` (open) | API key required in `X-API-Key` header; leave empty to disable auth |

Copy `.env.example` to `.env` and fill in your values.

---

## Configuration

```text
Omni-Graph/
├── exec.py                          # Terminal UI entrypoint
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── database-schema.jpeg
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

- **Separation of concerns** — Retrieval, access control, and orchestration are distinct modules; the agent composes them.
- **LLM-first, keyword fallback** — Claude extraction catches any entity; keyword lists ensure well-known tech terms are never missed.
- **SQL-as-contract** — FTS maintenance, audit emission, and taxonomy invariants are enforced by triggers and stored procedures.
- **Idempotent writes** — Hash dedup, `ON CONFLICT` upserts, and stable embedding keys make the pipeline safe to re-run.
- **Graceful degradation** — Embedding failures do not roll back document writes; LLM failures fall back to keyword extraction; FTS always works.
- **Provenance** — Every extracted relation stores `source_document_id`; every query is logged to `query_logs`.

---

## Sample Seed Users

Seeded by `sample_data.sql`: `agarwal.priya` · `chen.wei` · `johnson.mark` · `martinez.sofia` · `okafor.emeka` · `tanaka.yuki` · `williams.alex` · `kumar.rahul` · `fischer.anna` · `brown.david`

### Areas for Contribution

- SQL initialization order: `schema.sql` → `sample_data.sql` → `procedures_triggers.sql`. Docker handles this automatically.
- To grant `view_graph` permission to the admin role:

```sql
UPDATE omnigraph.roles
SET permissions = array_append(permissions, 'view_graph')
WHERE role_name = 'admin'
  AND NOT ('view_graph' = ANY(permissions));
```

---

## License

MIT — see [LICENSE](LICENSE).

---
## Contributers
<div align="center">

<a href="https://github.com/vaishcodescape/Omni-Graph/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=vaishcodescape/Omni-Graph" />
</a>


If you found this project useful, consider giving it a star!

</div>
