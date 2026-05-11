<div align="center">

<br/>

<h1>OmniGraph</h1>

<p><strong>Turn documents into a queryable knowledge graph — powered by Claude AI.</strong></p>

<p>
Ingest PDFs, URLs, and raw text · Extract entities & relationships with LLM-powered NLP ·<br/>
Search with hybrid full-text + vector + graph retrieval · Chat via an Anthropic AI agent ·<br/>
Plug directly into Claude Desktop as an MCP server.
</p>

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST_API-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D4A574?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![MCP](https://img.shields.io/badge/MCP-Server-8B5CF6?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

<br/>

<table>
  <tr>
    <td align="center"><h2>19</h2><sub>Database Tables</sub></td>
    <td align="center"><h2>13</h2><sub>MCP Tools</sub></td>
    <td align="center"><h2>4</h2><sub>Search Strategies</sub></td>
    <td align="center"><h2>1024</h2><sub>Vector Dimensions</sub></td>
    <td align="center"><h2>6</h2><sub>Stored Procedures</sub></td>
    <td align="center"><h2>3,500+</h2><sub>Lines of Python</sub></td>
  </tr>
</table>

<br/>

</div>

---

## What is OmniGraph?

OmniGraph is an **enterprise-grade knowledge graph platform** that transforms unstructured documents into a structured, searchable, and AI-queryable graph. Upload a PDF, paste a URL, or POST raw text — OmniGraph extracts every entity, concept, and relationship using Claude AI, stores them in a relational graph on PostgreSQL + pgvector, and makes everything instantly queryable through four search modes and a conversational AI agent.

It ships three interfaces out of the box:

| Interface | Best for |
|-----------|----------|
| **MCP Server** | Native Claude Desktop integration — Claude uses OmniGraph tools directly |
| **REST API** | Any client, any language — full Swagger docs at `/docs` |
| **Terminal UI** | Local exploration, demos, and development |

---

## Features

<table>
<tr>
<td width="50%">

### 🔍 Hybrid Search Engine
Four retrieval strategies unified behind a single weighted ranker. Full-text (`tsvector` + GIN), 1024-dim semantic vectors (Voyage AI), and entity-graph traversal — blended automatically in hybrid mode.

</td>
<td width="50%">

### 🤖 Agentic RAG
An Anthropic Claude agent with a native tool-use loop. It searches, reads, explores the graph, finds experts, and cites every factual claim with a `[doc_id=X]` reference — automatically.

</td>
</tr>
<tr>
<td>

### 🧠 LLM-Powered NLP Extraction
`claude-haiku-4-5` extracts entities, concepts, and typed relationships from any text. Keyword lists run in parallel as a safety net — nothing slips through.

</td>
<td>

### 🔌 Native MCP Server
13 tools, 3 resources, and 3 prompt templates — plug OmniGraph into Claude Desktop in 60 seconds. Claude can ingest, search, and reason over your knowledge graph without writing a line of code.

</td>
</tr>
<tr>
<td>

### 🏢 Enterprise Security Model
Role-based access control enforced at read time (not just write time) with four sensitivity tiers. Every query is post-filtered, every sensitive access is logged to an immutable audit trail.

</td>
<td>

### ⚡ One-Command Deploy
`docker compose up` — PostgreSQL + pgvector + the API server, schema auto-initialized from SQL files. No manual setup, no migration scripts.

</td>
</tr>
</table>

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph

cp .env.example .env
# Open .env and add your ANTHROPIC_API_KEY and VOYAGE_API_KEY

docker compose up
```

That's it. The API is live at **http://localhost:8000** and interactive Swagger docs are at **http://localhost:8000/docs**.

PostgreSQL schema, stored procedures, and seed data initialize automatically on first run.

<details>
<summary><strong>Local setup (without Docker)</strong></summary>
<br/>

```bash
# 1. Create and seed the database
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/sample_data.sql
psql -d omnigraph -f sql/procedures_triggers.sql

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env    # then fill in your API keys

# 4a. Run the REST API
uvicorn api.main:app --reload --port 8000

# 4b. Or run the terminal UI
python exec.py
```

</details>

---

## How It Works

Every document goes through a five-stage automated pipeline:

```
 Input (text / PDF / DOCX / URL)
        │
        ▼
 ┌─────────────────────────────────────────────────┐
 │  1. PARSE & NORMALIZE                           │
 │     Strip control chars · collapse whitespace   │
 └──────────────────────────┬──────────────────────┘
                            │
                            ▼
 ┌─────────────────────────────────────────────────┐
 │  2. DEDUPLICATE                                 │
 │     SHA-256 hash → skip if seen · version if   │
 │     content changed · always idempotent         │
 └──────────────────────────┬──────────────────────┘
                            │
                            ▼
 ┌─────────────────────────────────────────────────┐
 │  3. EMBED                                       │
 │     Voyage AI voyage-3 → 1024-dim vector →     │
 │     upsert into pgvector on (type, id, model)  │
 └──────────────────────────┬──────────────────────┘
                            │
                            ▼
 ┌─────────────────────────────────────────────────┐
 │  4. EXTRACT  (Claude Haiku + keyword fallback)  │
 │     Entities → document_entities               │
 │     Concepts → document_concepts               │
 │     Relations → directed graph edges           │
 └──────────────────────────┬──────────────────────┘
                            │
                            ▼
 ┌─────────────────────────────────────────────────┐
 │  5. QUERY-READY                                 │
 │     Full-text · Semantic · Graph · Hybrid       │
 │     All results RBAC-filtered at read time      │
 └─────────────────────────────────────────────────┘
```

---

## MCP Server — Claude Desktop in 60 Seconds

Add OmniGraph to your Claude Desktop config and Claude gains direct access to your knowledge graph:

**`~/.claude/claude_desktop_config.json`** (Mac/Linux) or **`%APPDATA%\Claude\claude_desktop_config.json`** (Windows):

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

Restart Claude Desktop — OmniGraph appears in the tools panel. A pre-filled example is in [`claude_desktop_config.example.json`](claude_desktop_config.example.json).

### MCP Tools

| Category | Tool | What it does |
|----------|------|--------------|
| **Search** | `search` | Hybrid / fulltext / semantic / graph search |
| | `read_document` | Fetch full document text by ID |
| | `find_experts` | Domain experts ranked by concept contribution |
| | `get_entity_documents` | All documents linked to a named entity |
| | `find_related_concepts` | Concept hierarchy + co-occurrence graph |
| **Ingest** | `ingest_document` | Add text to the knowledge graph |
| | `ingest_url` | Fetch a URL and ingest its content |
| **Explore** | `graph_stats` | Live entity / relation / concept counts |
| | `list_entities` | Browse entities with optional type filter |
| | `entity_neighborhood` | N-hop entity graph traversal |
| | `list_documents` | Paginated document listing |
| **Utility** | `extract_entities` | Analyze text without writing to DB |
| | `build_graph` | Backfill extraction on all unprocessed docs |

### MCP Prompts

Use these ready-made research workflows from the Claude Desktop prompt menu:

- **`research_topic`** — Searches documents, reads top results, explores related concepts, finds experts, synthesizes with citations
- **`analyze_document`** — Reads a document, extracts entities, finds related docs and experts
- **`explore_entity`** — Maps all entity connections, linked documents, and related concepts

---

## REST API

Full Swagger docs at **`/docs`** when the server is running. All `/api/v1/*` endpoints require an `X-API-Key` header (set `OMNIGRAPH_API_KEY` in `.env`; leave empty to disable auth in dev).

<details>
<summary><strong>View all endpoints</strong></summary>

<br/>

**Health & Auth**
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | DB ping, capability flags |
| `POST` | `/api/v1/auth/login` | Resolve username → `user_id` + roles |

**Documents**
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents/ingest` | Ingest plain text |
| `POST` | `/api/v1/documents/upload` | Upload PDF / DOCX / TXT |
| `POST` | `/api/v1/documents/ingest-url` | Fetch a URL and ingest |
| `GET` | `/api/v1/documents` | Paginated list with filters |
| `GET` | `/api/v1/documents/{id}` | Full document detail |
| `DELETE` | `/api/v1/documents/{id}` | Soft-archive |

**Search & Chat**
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/search` | hybrid / fulltext / semantic / graph |
| `POST` | `/api/v1/chat` | Ask the Claude agent, get cited answer |

**Graph**
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/graph/stats` | Entity / relation / concept counts |
| `GET` | `/api/v1/graph/entities` | Browse entities |
| `GET` | `/api/v1/graph/entities/{id}/neighborhood` | N-hop traversal |
| `POST` | `/api/v1/graph/build` | Backfill all unextracted documents |

</details>

### Usage examples

```bash
# Upload a PDF — text extracted automatically, entities extracted by Claude
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@research.pdf" -F "uploaded_by=1" -F "source_type=research_paper"

# Hybrid search
curl -X POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"query": "federated learning privacy", "strategy": "hybrid", "user_id": 1}'

# Ask the AI agent
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"message": "Who are the experts on Kubernetes?", "user_id": 1}'
```

---

## Python SDK

```python
from omnigraph import DatabaseConnection, DocumentIngester
from omnigraph import EntityRelationExtractor, SemanticQueryEngine, get_anthropic_agent

db = DatabaseConnection()  # reads all config from env vars
db.connect()

# 1. Ingest — deduplicates, embeds, and extracts automatically
ingester = DocumentIngester(db)
doc_id = ingester.ingest_document(
    title="Kubernetes in Production",
    source_type="technical_doc",
    content="Kubernetes orchestrates Docker containers across clusters...",
    uploaded_by=1,
    sensitivity_level="internal",
)

# 2. Extract entities and relationships with Claude Haiku
extractor = EntityRelationExtractor(db)
result = extractor.process_document(doc_id)
# result["entities"]      → [{name, entity_type, confidence, mention_count}]
# result["concepts"]      → [{name, domain, relevance_score}]
# result["relationships"] → [{source, target, relation_type, strength}]

# 3. Hybrid search — RBAC-filtered automatically
engine = SemanticQueryEngine(db, user_id=1)
hits = engine.search("container orchestration", strategy="hybrid", limit=5)

# 4. Conversational agent with citations
agent = get_anthropic_agent(db, user_id=1)
response = agent.run("Who are the leading experts on Kubernetes in this org?")
print(response["answer"])    # Answer with [doc_id=X] citations
print(response["citations"]) # [{document_id, title, source_type}]
```

---

## Database Design

19 tables in the `omnigraph` PostgreSQL schema, organized into five layers:

```
Identity & Access   roles · users · user_roles · access_policies
Content             documents · document_versions · taxonomy · tags · document_tags
Knowledge Graph     entities · relations · concepts · concept_hierarchy
                    entity_concepts · document_entities · document_concepts
Semantic Layer      embeddings  ← polymorphic: covers docs, entities, and concepts
Observability       query_logs · audit_logs
```

<div align="center">
<img src="./database-schema.jpeg" alt="OmniGraph ER diagram" width="860"/>
</div>

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| **Polymorphic embeddings** | One `embeddings` table spans documents, entities, and concepts via `(source_type, source_id)` — uniform semantic search across all node types |
| **Directed relations with provenance** | Every `relations` row stores `source_document_id` — every edge is auditable back to the document that generated it |
| **Row-level sensitivity enforcement** | `documents.sensitivity_level` is re-checked at read time by `AccessControlManager` — not just at write time |
| **Shortest-path BFS in SQL** | `sp_shortest_path()` implemented as a recursive-CTE PostgreSQL function — no application-side graph library needed |
| **SHA-256 deduplication** | Content hash stored on write; duplicate detection is a single indexed lookup with zero application logic |

---

## Search Strategies

| Strategy | Mechanism | Best for |
|----------|-----------|----------|
| `fulltext` | PostgreSQL `tsvector` / `tsquery`, GIN-indexed | Exact keywords, acronyms, IDs |
| `semantic` | Voyage AI `voyage-3` → pgvector cosine distance | Natural-language questions, synonyms |
| `graph` | Entity → relation → entity → document traversal | "What else connects to X?" |
| `hybrid` ✦ | Weighted blend `{fulltext: 1.0, semantic: 1.2, graph: 0.8}` | Production default |

Every result is post-filtered through RBAC — users only receive documents they have `read` access to.

---

## Engineering Practices

- **LLM-first, never LLM-only** — Claude extraction handles open-ended entities; keyword lists run in parallel to guarantee well-known tech terms are always captured
- **Idempotent by default** — SHA-256 dedup, `ON CONFLICT` upserts on all graph writes, stable embedding keys mean the pipeline is safe to re-run at any time
- **SQL as the contract** — FTS tsvector maintenance, taxonomy level computation, and audit log emission are enforced by triggers — not ad-hoc application code
- **Graceful degradation** — Embedding failures never roll back document writes; LLM extraction failures fall back to keyword mode; full-text search is always available
- **Provenance everywhere** — Every extracted relation stores `source_document_id`; every search query is timed and logged to `query_logs`
- **Separation of concerns** — Retrieval, RBAC, extraction, and agent orchestration are four independent modules that compose without coupling

---

## Tech Stack

<div align="center">

<table>
<tr>
<td align="center" width="100">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" width="48" height="48" alt="Python"/><br/><b>Python</b>
</td>
<td align="center" width="100">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="48" height="48" alt="PostgreSQL"/><br/><b>PostgreSQL</b>
</td>
<td align="center" width="100">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/fastapi/fastapi-original.svg" width="48" height="48" alt="FastAPI"/><br/><b>FastAPI</b>
</td>
<td align="center" width="100">
<img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/docker/docker-original.svg" width="48" height="48" alt="Docker"/><br/><b>Docker</b>
</td>
<td align="center" width="100">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/anthropic/white"/>
<img src="https://upload.wikimedia.org/wikipedia/commons/7/78/Anthropic_logo.svg" width="48" height="48" alt="Anthropic"/>
</picture>
<br/><b>Claude AI</b>
</td>
</tr>
</table>

</div>

| Layer | Technology |
|:------|:-----------|
| Language | Python 3.11+ |
| REST API | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector |
| Embeddings | Voyage AI `voyage-3` (1024-dim cosine) |
| LLM Agent | Anthropic Claude (tool-use + streaming) |
| NLP Extraction | `claude-haiku-4-5` + keyword/regex fallback |
| File Parsing | pdfminer.six · python-docx · httpx + BeautifulSoup4 |
| MCP | Model Context Protocol SDK (`mcp>=1.0`) |
| Deployment | Docker + docker-compose |

---

## Project Structure

```
Omni-Graph/
│
├── mcp_server/
│   └── server.py                 ← MCP server: 13 tools, 3 resources, 3 prompts
│
├── api/
│   ├── main.py                   ← FastAPI app: all 13 REST endpoints
│   ├── file_parser.py            ← PDF / DOCX / URL extraction
│   ├── models.py                 ← Pydantic schemas
│   ├── auth.py                   ← API-key middleware
│   └── dependencies.py           ← DB dependency injection
│
├── omnigraph/
│   ├── ingestion_pipeline.py     ← Normalize · deduplicate · version · embed
│   ├── entity_relation_extractor.py  ← Claude NLP + keyword fallback
│   ├── graph_builder.py          ← Entity/relation CRUD · auto-backfill
│   ├── semantic_query_engine.py  ← Fulltext / vector / graph / hybrid search
│   ├── access_control_audit.py   ← RBAC · sensitivity · audit logging
│   ├── agentic_rag.py            ← Claude tool-use agent
│   ├── embedder.py               ← Voyage AI wrapper
│   └── console_app.py            ← ANSI terminal UI
│
├── sql/
│   ├── schema.sql                ← 19 tables, constraints, indexes
│   ├── procedures_triggers.sql   ← 6 stored procedures + 5 triggers
│   ├── sample_data.sql           ← Seed users, roles, documents
│   └── retrieval.sql             ← Advanced query examples
│
├── exec.py                       ← Terminal UI entrypoint
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── claude_desktop_config.example.json
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values.

| Variable | Default | Required |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | — | ✅ For Claude agent + LLM extraction |
| `VOYAGE_API_KEY` | — | ✅ For semantic / vector search |
| `OMNIGRAPH_API_KEY` | *(empty — open)* | For REST API auth |
| `OMNIGRAPH_DB_HOST` | `localhost` | For non-Docker deployments |
| `OMNIGRAPH_DB_PORT` | `5432` | |
| `OMNIGRAPH_DB_NAME` | `omnigraph` | |
| `OMNIGRAPH_DB_USER` | `postgres` | |
| `OMNIGRAPH_DB_PASSWORD` | `postgres` | |
| `OMNIGRAPH_DEFAULT_USER_ID` | `1` | MCP server RBAC context |

---

## Contributing

Contributions are welcome! To get started:

1. Fork the repo and create a feature branch from `main`
2. Run the local setup above and verify the existing functionality works
3. Make your changes — keep PRs focused on a single concern
4. Open a pull request with a clear description of what you changed and why

**Good first issues:** improving test coverage, adding new MCP tools, supporting additional file formats (e.g. PPTX, CSV), or writing a frontend UI.

---

## License

MIT — see [LICENSE](LICENSE). Use freely, attribution appreciated.

---

<div align="center">

Built with [Anthropic Claude](https://anthropic.com) · [pgvector](https://github.com/pgvector/pgvector) · [FastAPI](https://fastapi.tiangolo.com) · [Model Context Protocol](https://modelcontextprotocol.io)

⭐ **Star this repo** if you find it useful!

</div>
