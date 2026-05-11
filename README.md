<div align="center">

<h1>OmniGraph</h1>

<p><strong>Turn any document into a queryable knowledge graph</strong></p>

<p>
Ingest PDFs, URLs, and raw text &nbsp;·&nbsp; Extract entities &amp; relationships with LLM NLP &nbsp;·&nbsp; Search with hybrid full-text + vector + graph retrieval &nbsp;·&nbsp; Chat via an Anthropic agent &nbsp;·&nbsp; Plug into Claude Desktop via MCP
</p>

[![Python](https://img.shields.io/badge/Python-3.11+-0d1117?style=flat-square&logo=python&logoColor=3776AB)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-0d1117?style=flat-square&logo=postgresql&logoColor=4169E1)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0d1117?style=flat-square&logo=fastapi&logoColor=009688)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-0d1117?style=flat-square&logo=docker&logoColor=2496ED)](https://docs.docker.com/compose/)
[![Anthropic](https://img.shields.io/badge/Claude_AI-0d1117?style=flat-square&logo=anthropic&logoColor=D4A574)](https://www.anthropic.com/)
[![MCP](https://img.shields.io/badge/MCP_Server-0d1117?style=flat-square&logo=anthropic&logoColor=8B5CF6)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-0d1117?style=flat-square&logoColor=22C55E)](LICENSE)

</div>

---

## What it does

- **Ingests** PDFs, DOCX, URLs, and raw text — deduplicates via SHA-256, versions changed content
- **Extracts** named entities, typed relationships, and concepts using `claude-haiku-4-5` with a keyword fallback
- **Stores** everything in a 19-table PostgreSQL schema with `pgvector` for 1024-dim embeddings
- **Serves** hybrid search (full-text + semantic + graph), a Claude RAG agent with citations, a REST API, and a native MCP server for Claude Desktop

---

## Quick Start

**Docker — recommended, zero setup:**

```bash
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph
cp .env.example .env          # add ANTHROPIC_API_KEY + VOYAGE_API_KEY
docker compose up
```

API live at `http://localhost:8000` · Swagger at `http://localhost:8000/docs`

<details>
<summary><strong>Local setup (no Docker)</strong></summary>
<br/>

```bash
# 1. Postgres with pgvector extension
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/procedures_triggers.sql
psql -d omnigraph -f sql/sample_data.sql

# 2. Python deps
pip install -r requirements.txt
cp .env.example .env          # fill in your keys

# 3a. Run the REST API
uvicorn api.main:app --reload --port 8000

# 3b. Or the terminal UI
python exec.py
```

</details>

---

## Architecture

Every document goes through a five-stage pipeline:

```
Input (text / PDF / DOCX / URL)
        │
        ▼
┌───────────────────────────────────┐
│  1. PARSE & NORMALIZE             │  api/file_parser.py
│     Strip noise · collapse space  │
└────────────────┬──────────────────┘
                 │
                 ▼
┌───────────────────────────────────┐
│  2. DEDUPLICATE                   │  omnigraph/ingestion_pipeline.py
│     SHA-256 hash → skip / version │
└────────────────┬──────────────────┘
                 │
                 ▼
┌───────────────────────────────────┐
│  3. EMBED                         │  omnigraph/embedder.py
│     Voyage AI voyage-3 → 1024-dim │
│     upsert into pgvector          │
└────────────────┬──────────────────┘
                 │
                 ▼
┌───────────────────────────────────┐
│  4. EXTRACT  (LLM + fallback)     │  omnigraph/entity_relation_extractor.py
│     Entities · Concepts · Relations│
└────────────────┬──────────────────┘
                 │
                 ▼
┌───────────────────────────────────┐
│  5. QUERY-READY                   │  omnigraph/semantic_query_engine.py
│     Fulltext · Semantic · Graph   │
│     · Hybrid  (RBAC-filtered)     │
└───────────────────────────────────┘
```

### Codebase map

```
Omni-Graph/
├── mcp_server/server.py              ← MCP: 13 tools, 3 resources, 3 prompts
├── api/
│   ├── main.py                       ← FastAPI: 13 REST endpoints
│   ├── file_parser.py                ← PDF / DOCX / URL text extraction
│   ├── models.py                     ← Pydantic request/response schemas
│   ├── auth.py                       ← X-API-Key middleware
│   └── dependencies.py               ← DB dependency injection
├── omnigraph/
│   ├── ingestion_pipeline.py         ← Normalize · deduplicate · embed
│   ├── entity_relation_extractor.py  ← Claude NLP + keyword fallback
│   ├── graph_builder.py              ← Entity/relation CRUD + backfill
│   ├── semantic_query_engine.py      ← Fulltext / vector / graph / hybrid
│   ├── access_control_audit.py       ← RBAC · sensitivity · audit log
│   ├── agentic_rag.py                ← Claude tool-use agent loop
│   ├── embedder.py                   ← Voyage AI wrapper
│   └── console_app.py                ← ANSI terminal UI
└── sql/
    ├── schema.sql                    ← 19 tables, indexes, constraints
    ├── procedures_triggers.sql       ← 6 stored procedures + 5 triggers
    ├── sample_data.sql               ← Seed users, roles, documents
    └── retrieval.sql                 ← Advanced query examples
```

---

## Contributing

Contributions are welcome. Here is the fastest path from zero to a merged PR.

### 1. Set up your dev environment

```bash
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph
pip install -r requirements.txt
cp .env.example .env    # add your keys
docker compose up -d    # start postgres only is fine
```

### 2. Find something to work on

| Label | Examples |
|-------|---------|
| `good first issue` | Additional file formats (PPTX, CSV, Markdown), better error messages, extra curl examples in docs |
| `enhancement` | New MCP tools, streaming chat responses, frontend UI, OpenTelemetry traces |
| `bug` | Check the [Issues tab](https://github.com/vaishcodescape/Omni-Graph/issues) |

### 3. Branch and PR conventions

- Branch from `main`: `feat/...`, `fix/...`, `docs/...`
- Keep PRs focused on one concern — easier to review and bisect
- Add a short description of *why*, not just *what*

### 4. Key interfaces to know

| Module | Entry point | What to change |
|--------|------------|----------------|
| Add a new MCP tool | `mcp_server/server.py` → `list_tools()` + `call_tool()` | Follow existing handler pattern |
| Add a REST endpoint | `api/main.py` | Add Pydantic model in `api/models.py` |
| New file format | `api/file_parser.py` → `parse_file()` dispatcher | Add a `parse_xyz()` function |
| Change extraction | `omnigraph/entity_relation_extractor.py` | `_LLM_EXTRACTION_PROMPT` or `_extract_keywords()` |
| New search strategy | `omnigraph/semantic_query_engine.py` | `_search_*()` + `search()` router |

---

## MCP — Claude Desktop integration

Add to `~/.claude/claude_desktop_config.json` (Mac/Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

Restart Claude Desktop — OmniGraph appears in the tools panel.

<details>
<summary><strong>All 13 MCP tools</strong></summary>
<br/>

| Category | Tool | Description |
|----------|------|-------------|
| **Search** | `search` | Hybrid / fulltext / semantic / graph |
| | `read_document` | Fetch full document text by ID |
| | `find_experts` | Domain experts ranked by concept contribution |
| | `get_entity_documents` | All documents linked to a named entity |
| | `find_related_concepts` | Concept hierarchy + co-occurrence graph |
| **Ingest** | `ingest_document` | Add text to the graph |
| | `ingest_url` | Fetch a URL and ingest its content |
| **Explore** | `graph_stats` | Live entity / relation / concept counts |
| | `list_entities` | Browse entities with optional type filter |
| | `entity_neighborhood` | N-hop entity graph traversal |
| | `list_documents` | Paginated document listing |
| **Utility** | `extract_entities` | Analyze text without writing to DB |
| | `build_graph` | Backfill extraction on all unprocessed docs |

**Prompt templates** (from the Claude Desktop prompt menu):

- `research_topic` — search, read top results, explore concepts, synthesize with citations
- `analyze_document` — read doc, extract entities, find related docs and experts
- `explore_entity` — map all connections, linked documents, related concepts

</details>

---

## REST API

Full interactive docs at **`/docs`** when the server is running.

Auth: `X-API-Key` header — set `OMNIGRAPH_API_KEY` in `.env` (leave empty to disable in dev).

<details>
<summary><strong>All endpoints</strong></summary>
<br/>

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | DB ping + capability flags |
| `POST` | `/api/v1/auth/login` | Resolve username → user_id + roles |
| `POST` | `/api/v1/documents/ingest` | Ingest plain text |
| `POST` | `/api/v1/documents/upload` | Upload PDF / DOCX / TXT |
| `POST` | `/api/v1/documents/ingest-url` | Fetch a URL and ingest |
| `GET` | `/api/v1/documents` | Paginated list with filters |
| `GET` | `/api/v1/documents/{id}` | Full document detail |
| `DELETE` | `/api/v1/documents/{id}` | Soft-archive |
| `POST` | `/api/v1/search` | hybrid / fulltext / semantic / graph |
| `POST` | `/api/v1/chat` | Ask the Claude agent, get cited answer |
| `GET` | `/api/v1/graph/stats` | Entity / relation / concept counts |
| `GET` | `/api/v1/graph/entities` | Browse entities |
| `GET` | `/api/v1/graph/entities/{id}/neighborhood` | N-hop traversal |
| `POST` | `/api/v1/graph/build` | Backfill all unextracted documents |

</details>

```bash
# Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@report.pdf" -F "uploaded_by=1" -F "source_type=research_paper"

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

## Database design

19 tables organized in five layers:

```
Identity & Access   roles · users · user_roles · access_policies
Content             documents · document_versions · taxonomy · tags · document_tags
Knowledge Graph     entities · relations · concepts · concept_hierarchy
                    entity_concepts · document_entities · document_concepts
Semantic Layer      embeddings  (polymorphic across docs, entities, concepts)
Observability       query_logs · audit_logs
```

<div align="center">
<img src="./database-schema.jpeg" alt="OmniGraph ER diagram" width="860"/>
</div>

| Decision | Why |
|----------|-----|
| Polymorphic `embeddings` table | One table spans docs, entities, and concepts via `(source_type, source_id)` — uniform semantic search everywhere |
| Directed relations with provenance | Every `relations` row stores `source_document_id` — every edge is auditable |
| Row-level sensitivity enforcement | `sensitivity_level` re-checked at read time, not just write time |
| Shortest-path BFS in SQL | Recursive-CTE PostgreSQL function — no application-side graph library |
| SHA-256 deduplication | Content hash on write; duplicate detection is a single indexed lookup |

---

## Search strategies

| Strategy | Mechanism | Best for |
|----------|-----------|----------|
| `fulltext` | `tsvector` + `tsquery`, GIN-indexed | Exact keywords, acronyms, IDs |
| `semantic` | Voyage AI `voyage-3` → pgvector cosine | Natural language, synonyms |
| `graph` | Entity → relation → document traversal | "What else connects to X?" |
| `hybrid` | Weighted blend `{fulltext: 1.0, semantic: 1.2, graph: 0.8}` | Production default |

---

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `ANTHROPIC_API_KEY` | — | Required for Claude agent + LLM extraction |
| `VOYAGE_API_KEY` | — | Required for semantic / vector search |
| `OMNIGRAPH_API_KEY` | *(empty)* | REST API auth; empty = open in dev |
| `OMNIGRAPH_DB_HOST` | `localhost` | Use container name in Docker |
| `OMNIGRAPH_DB_PORT` | `5432` | |
| `OMNIGRAPH_DB_NAME` | `omnigraph` | |
| `OMNIGRAPH_DB_USER` | `postgres` | |
| `OMNIGRAPH_DB_PASSWORD` | `postgres` | |
| `OMNIGRAPH_DEFAULT_USER_ID` | `1` | MCP server RBAC context |

---

 

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

Built with [Claude AI](https://anthropic.com) · [pgvector](https://github.com/pgvector/pgvector) · [FastAPI](https://fastapi.tiangolo.com) · [Model Context Protocol](https://modelcontextprotocol.io)

⭐ **Star this repo** if OmniGraph saves you time!

</div>
