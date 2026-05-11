<div align="center">

<img src="./database-schema.jpeg" alt="OmniGraph" width="860" />

### AI-Powered Knowledge Graph Platform

[![GitHub stars](https://img.shields.io/github/stars/vaishcodescape/Omni-Graph?style=flat&logo=github)](https://github.com/vaishcodescape/Omni-Graph/stargazers)
[![License](https://img.shields.io/github/license/vaishcodescape/Omni-Graph?style=flat)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/vaishcodescape/Omni-Graph?style=flat&logo=github)](https://github.com/vaishcodescape/Omni-Graph/issues)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-555?logo=linkedin)](https://linkedin.com/in/adityavaish)

<br />

Transform unstructured documents into a structured, searchable, AI-queryable knowledge graph.<br />
Ingest PDFs, DOCX, URLs, or raw text. Query with four search strategies, a RAG agent, or Claude Desktop.

<br />

[**Quick Start**](#getting-started) &nbsp;&bull;&nbsp; [API Docs (localhost)](http://localhost:8000/docs) &nbsp;&bull;&nbsp; [Report Bug](https://github.com/vaishcodescape/Omni-Graph/issues/new?labels=bug) &nbsp;&bull;&nbsp; [Request Feature](https://github.com/vaishcodescape/Omni-Graph/issues/new?labels=enhancement)

<br />

</div>

## Build Knowledge Graphs From Any Document

OmniGraph ingests documents, extracts entities and relationships using Claude AI, embeds everything with Voyage AI, and stores it in a 19-table PostgreSQL schema with pgvector. Three interfaces share the same core engine -- nothing is locked to a single client.

- **Ingest anything** -- PDF, DOCX, URL, or plain text with SHA-256 deduplication and automatic versioning
- **Extract knowledge automatically** -- Claude Haiku pulls entities, typed relationships, and concepts with confidence scores
- **Search four ways** -- fulltext, semantic, graph traversal, and weighted hybrid with RBAC post-filtering
- **Ask questions with citations** -- conversational RAG agent powered by Claude Opus tool-use loop
- **Plug into Claude Desktop** -- 13-tool MCP server, no REST calls or glue code required

## Features

| Feature | Description |
|:--------|:------------|
| **Document Ingestion** | PDF, DOCX, URL, and text parsing with normalization and dedup |
| **AI Entity Extraction** | Claude Haiku NLP with keyword fallback when LLM is unavailable |
| **Hybrid Search** | Fulltext + semantic + graph retrieval with weighted rank merging |
| **Agentic RAG** | Claude Opus tool-use agent that returns cited answers |
| **MCP Server** | 13 tools, 3 resources, 3 prompt templates for Claude Desktop |
| **REST API** | 14 FastAPI endpoints with Swagger docs and API-key auth |
| **Terminal UI** | Interactive console app with menus for all operations |
| **Access Control** | RBAC with 4 sensitivity tiers, row-level enforcement, audit log |
| **Graph Traversal** | Recursive-CTE shortest-path BFS, N-hop neighborhood queries |
| **Idempotent Pipeline** | SHA-256 dedup + `ON CONFLICT` upserts -- safe to re-run anytime |

## Search Strategies

| Strategy | Mechanism | Best for |
|:---------|:----------|:---------|
| `fulltext` | PostgreSQL `tsvector` / `tsquery` with GIN indexes | Exact keywords, acronyms, IDs |
| `semantic` | Voyage AI `voyage-3` embeddings, pgvector cosine distance | Natural-language questions, synonyms |
| `graph` | Entity-relation-document traversal | "What else connects to X?" |
| `hybrid` | Weighted blend of all three | General-purpose production queries |

Every result is post-filtered through role-based access control. Users only see documents matching their sensitivity clearance.

## Interfaces

OmniGraph exposes three interfaces. All share the same core engine.

| Interface | Tools / Endpoints | Auth |
|:----------|:------------------|:-----|
| **REST API** | 14 endpoints at `/api/v1/*` | API-key header |
| **MCP Server** | 13 tools + 3 resources + 3 prompts | Claude Desktop config |
| **Terminal UI** | Interactive menus | Local access |

<details>
<summary>All 14 REST endpoints</summary>
<br />

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

<details>
<summary>All 13 MCP tools</summary>
<br />

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
<summary>MCP prompt templates</summary>
<br />

- **`research_topic`** -- Search documents, read top results, explore related concepts, find experts, synthesize an answer with citations.
- **`analyze_document`** -- Read a document by ID, extract entities, find related documents and domain experts.
- **`explore_entity`** -- Map all connections for a named entity: linked documents, relationships, related concepts.

</details>

## Requirements

| Requirement | Details |
|:------------|:--------|
| **OS** | macOS / Linux (Windows via WSL) |
| **Runtime** | Python 3.11+ |
| **Database** | PostgreSQL 16 with pgvector extension |
| **API Keys** | [Anthropic](https://console.anthropic.com/) + [Voyage AI](https://www.voyageai.com/) |
| **Optional** | [Docker](https://docs.docker.com/get-docker/) for one-command setup |

## Getting Started

### Docker (Recommended)

```bash
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph
cp .env.example .env          # add your ANTHROPIC_API_KEY and VOYAGE_API_KEY
docker compose up
```

The API is live at `http://localhost:8000` with interactive Swagger docs at `/docs`. PostgreSQL schema, stored procedures, and seed data initialize automatically on first run.

### Manual Setup

<details>
<summary>Click to expand manual setup instructions</summary>

**1. Create and initialize the database**

```bash
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/procedures_triggers.sql
psql -d omnigraph -f sql/sample_data.sql
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure environment**

```bash
cp .env.example .env    # fill in API keys
```

**4. Run**

```bash
uvicorn api.main:app --reload --port 8000    # REST API
python exec.py                                # or terminal UI
```

</details>

## Usage

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

### Claude Desktop Integration

Add to `~/.claude/claude_desktop_config.json`:

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

## Database Schema

19 tables normalized to BCNF, organized in five layers: Identity & Access, Content, Knowledge Graph, Semantic Layer, and Observability.

| Decision | Rationale |
|:---------|:----------|
| Polymorphic embeddings table | Single `embeddings` table covers documents, entities, and concepts via `(source_type, source_id)` |
| Directed relations with provenance | Every graph edge is auditable back to the document that created it |
| Row-level sensitivity enforcement | Four tiers (public, internal, confidential, restricted) re-checked at read time |
| Shortest-path BFS in SQL | Recursive-CTE PostgreSQL function -- no application-side graph library |
| SHA-256 content deduplication | Content-addressed storage, duplicate detection is a single indexed lookup |

## Project Structure

```
Omni-Graph/
├── mcp_server/
│   └── server.py                       MCP server (13 tools, 3 resources, 3 prompts)
├── api/
│   ├── main.py                         FastAPI application (14 REST endpoints)
│   ├── file_parser.py                  PDF / DOCX / URL content extraction
│   ├── models.py                       Pydantic request and response schemas
│   ├── auth.py                         API-key authentication middleware
│   └── dependencies.py                 Database connection dependency injection
├── omnigraph/
│   ├── ingestion_pipeline.py           Normalize, deduplicate, version, embed
│   ├── entity_relation_extractor.py    Claude NLP extraction + keyword fallback
│   ├── graph_builder.py                Entity/relation CRUD and auto-backfill
│   ├── semantic_query_engine.py        Fulltext, vector, graph, hybrid search
│   ├── access_control_audit.py         RBAC, sensitivity tiers, audit logging
│   ├── agentic_rag.py                  Claude tool-use agent loop
│   ├── embedder.py                     Voyage AI embedding wrapper
│   └── console_app.py                  Interactive terminal UI
├── sql/
│   ├── schema.sql                      19 tables, constraints, 25+ indexes
│   ├── procedures_triggers.sql         6 stored procedures, 5 triggers
│   ├── sample_data.sql                 Seed users, roles, and documents
│   └── retrieval.sql                   Advanced query examples
├── docker-compose.yml                  PostgreSQL (pgvector) + API server
├── Dockerfile                          Python 3.11-slim, uvicorn with 2 workers
├── requirements.txt
├── .env.example
└── claude_desktop_config.example.json
```

## Tech Stack

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python_3.11-14191f?logo=python&logoColor=3776AB" alt="Python" /></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL_16-14191f?logo=postgresql&logoColor=4169E1" alt="PostgreSQL" /></a>
  <a href="https://github.com/pgvector/pgvector"><img src="https://img.shields.io/badge/pgvector-14191f?logo=postgresql&logoColor=6366F1" alt="pgvector" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-14191f?logo=fastapi&logoColor=009688" alt="FastAPI" /></a>
  <a href="https://docs.docker.com/compose/"><img src="https://img.shields.io/badge/Docker-14191f?logo=docker&logoColor=2496ED" alt="Docker" /></a>
  <a href="https://www.anthropic.com/"><img src="https://img.shields.io/badge/Claude_AI-14191f?logo=anthropic&logoColor=D4A574" alt="Claude AI" /></a>
  <a href="https://www.voyageai.com/"><img src="https://img.shields.io/badge/Voyage_AI-14191f?logo=voyager&logoColor=A78BFA" alt="Voyage AI" /></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-14191f?logo=anthropic&logoColor=8B5CF6" alt="MCP" /></a>
</p>

## Roadmap

- [x] Document ingestion pipeline (PDF, DOCX, URL, text)
- [x] Claude-powered entity and relationship extraction
- [x] Four search strategies (fulltext, semantic, graph, hybrid)
- [x] Conversational RAG agent with citations
- [x] MCP server for Claude Desktop integration
- [x] REST API with Swagger docs
- [x] Role-based access control with audit logging
- [x] Docker Compose deployment
- [ ] Additional file formats (PPTX, CSV, Markdown)
- [ ] Test coverage
- [ ] Streaming chat responses
- [ ] Frontend UI

See the [open issues](https://github.com/vaishcodescape/Omni-Graph/issues) for a full list of proposed features and known issues.

## Contributing

We welcome contributions! If you have a suggestion that would make OmniGraph better:

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

You can also [open issues](https://github.com/vaishcodescape/Omni-Graph/issues) for bugs or feature requests.

**Where to start:**

| If you want to... | Look at |
|:-------------------|:--------|
| Add an MCP tool | `mcp_server/server.py` |
| Add a REST endpoint | `api/main.py` + `api/models.py` |
| Support a new file format | `api/file_parser.py` |
| Change entity extraction | `omnigraph/entity_relation_extractor.py` |
| Add a search strategy | `omnigraph/semantic_query_engine.py` |

<a href="https://github.com/vaishcodescape/Omni-Graph/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=vaishcodescape/Omni-Graph" />
</a>

## Contact

Aditya Vaish - adityavaish846@gmail.com

[![LinkedIn](https://img.shields.io/badge/LinkedIn-555?logo=linkedin)](https://linkedin.com/in/adityavaish)
[![GitHub](https://img.shields.io/badge/GitHub-555?logo=github)](https://github.com/vaishcodescape)

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
