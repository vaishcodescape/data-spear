<a name="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]



<!-- PROJECT LOGO -->
<br />
<div align="center">

  <h1>OmniGraph</h1>

  <p align="center">
    An enterprise knowledge graph platform that transforms unstructured documents into a structured, searchable, AI-queryable graph.
    <br />
    <br />
    <a href="https://github.com/vaishcodescape/Omni-Graph/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/vaishcodescape/Omni-Graph/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#docker-recommended">Docker (Recommended)</a></li>
        <li><a href="#manual-setup">Manual Setup</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#rest-api">REST API</a></li>
        <li><a href="#mcp-server----claude-desktop-integration">MCP Server</a></li>
        <li><a href="#search-strategies">Search Strategies</a></li>
      </ul>
    </li>
    <li><a href="#database-schema">Database Schema</a></li>
    <li><a href="#project-structure">Project Structure</a></li>
    <li><a href="#configuration">Configuration</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

Ingest PDFs, DOCX files, URLs, or raw text. OmniGraph parses, deduplicates, embeds, and extracts entities and relationships using Claude AI, then stores everything in a 19-table PostgreSQL schema with pgvector. Query the graph through four search strategies, a conversational RAG agent with citations, or plug it directly into Claude Desktop as an MCP server.

**Core capabilities:**

* **Document ingestion** -- PDF, DOCX, URL, and plain text with SHA-256 deduplication and automatic versioning
* **AI-powered extraction** -- Claude Haiku extracts entities, typed relationships, and concepts with confidence scores; keyword fallback when LLM is unavailable
* **Four search strategies** -- fulltext, semantic (Voyage AI embeddings), graph traversal, and weighted hybrid
* **Conversational RAG** -- Claude Opus tool-use agent loop that returns cited answers from the knowledge graph
* **Three interfaces** -- REST API (14 endpoints), MCP server (13 tools), and interactive terminal UI
* **Access control** -- Role-based access with four sensitivity tiers (public, internal, confidential, restricted), enforced at read time with immutable audit logging

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

[![Python][Python-shield]][Python-url]
[![PostgreSQL][PostgreSQL-shield]][PostgreSQL-url]
[![pgvector][pgvector-shield]][pgvector-url]
[![FastAPI][FastAPI-shield]][FastAPI-url]
[![Docker][Docker-shield]][Docker-url]
[![Anthropic][Anthropic-shield]][Anthropic-url]
[![Voyage AI][VoyageAI-shield]][VoyageAI-url]
[![MCP][MCP-shield]][MCP-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

* [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (for the recommended setup)
* An [Anthropic API key](https://console.anthropic.com/) for Claude-powered entity extraction and RAG
* A [Voyage AI API key](https://www.voyageai.com/) for semantic embeddings

### Docker (Recommended)

1. Clone the repo
   ```sh
   git clone https://github.com/vaishcodescape/Omni-Graph.git
   cd Omni-Graph
   ```
2. Configure environment variables
   ```sh
   cp .env.example .env
   ```
3. Add your API keys to `.env`
   ```env
   ANTHROPIC_API_KEY=sk-ant-...
   VOYAGE_API_KEY=pa-...
   ```
4. Start the services
   ```sh
   docker compose up
   ```

The API is live at `http://localhost:8000` with interactive Swagger docs at `/docs`. PostgreSQL schema, stored procedures, and seed data initialize automatically on first run.

### Manual Setup

1. Create and initialize the database
   ```sh
   createdb omnigraph
   psql -d omnigraph -f sql/schema.sql
   psql -d omnigraph -f sql/procedures_triggers.sql
   psql -d omnigraph -f sql/sample_data.sql
   ```
2. Install dependencies
   ```sh
   pip install -r requirements.txt
   ```
3. Configure environment
   ```sh
   cp .env.example .env    # fill in API keys
   ```
4. Run
   ```sh
   uvicorn api.main:app --reload --port 8000    # REST API
   python exec.py                                # or terminal UI
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE -->
## Usage

### REST API

Interactive docs at `/docs` when the server is running. All `/api/v1/*` endpoints require an `X-API-Key` header (set via `OMNIGRAPH_API_KEY` in `.env`; leave empty to disable auth in development).

```bash
# Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-API-Key: changeme" \
  -F "file=@paper.pdf" -F "uploaded_by=1" -F "source_type=research_paper"

# Hybrid search
curl -X POST http://localhost:8000/api/v1/search \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"query": "federated learning privacy", "strategy": "hybrid", "user_id": 1}'

# Ask the RAG agent
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: changeme" -H "Content-Type: application/json" \
  -d '{"message": "Who are the experts on Kubernetes?", "user_id": 1}'
```

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

### MCP Server -- Claude Desktop Integration

Add OmniGraph to Claude Desktop and Claude gets direct access to the knowledge graph. No REST calls, no glue code.

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

- **`research_topic`** -- Search documents, read top results, explore related concepts, find experts, synthesize an answer with citations.
- **`analyze_document`** -- Read a document by ID, extract entities, find related documents and domain experts.
- **`explore_entity`** -- Map all connections for a named entity: linked documents, relationships, related concepts.

</details>

### Search Strategies

OmniGraph supports four retrieval modes. Hybrid is the production default.

| Strategy | Mechanism | Best for |
|:---------|:----------|:---------|
| `fulltext` | PostgreSQL `tsvector` / `tsquery` with GIN indexes | Exact keywords, acronyms, IDs |
| `semantic` | Voyage AI `voyage-3` embeddings, pgvector cosine distance | Natural-language questions, synonyms |
| `graph` | Entity-relation-document traversal | "What else connects to X?" |
| `hybrid` | Weighted blend of all three | General-purpose production queries |

Every result is post-filtered through role-based access control. Users only see documents matching their sensitivity clearance.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- DATABASE SCHEMA -->
## Database Schema

19 tables normalized to BCNF, organized in five layers: Identity & Access, Content, Knowledge Graph, Semantic Layer, and Observability.

<div align="center">
<img src="./database-schema.jpeg" alt="OmniGraph ER diagram" width="860"/>
</div>

<br/>

| Decision | Rationale |
|:---------|:----------|
| Polymorphic embeddings table | Single `embeddings` table covers documents, entities, and concepts via `(source_type, source_id)`. Uniform semantic search across all node types. |
| Directed relations with provenance | Every `relations` row stores `source_document_id`. Every graph edge is auditable back to the document that created it. |
| Row-level sensitivity enforcement | `sensitivity_level` is re-checked at read time by `AccessControlManager`, not just at write time. Four tiers: public, internal, confidential, restricted. |
| Shortest-path BFS in SQL | `sp_shortest_path()` is a recursive-CTE PostgreSQL function. No application-side graph library required. |
| SHA-256 content deduplication | Hash computed on write; duplicate detection is a single indexed lookup. Re-ingesting the same content is a no-op. |

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- PROJECT STRUCTURE -->
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

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONFIGURATION -->
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

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
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

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feat/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feat/AmazingFeature`)
5. Open a Pull Request

**Where to start:**

| If you want to... | Look at |
|:-------------------|:--------|
| Add an MCP tool | `mcp_server/server.py` |
| Add a REST endpoint | `api/main.py` + `api/models.py` |
| Support a new file format | `api/file_parser.py` |
| Change entity extraction | `omnigraph/entity_relation_extractor.py` |
| Add a search strategy | `omnigraph/semantic_query_engine.py` |

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Aditya Vaish - adityavaish846@gmail.com

Project Link: [https://github.com/vaishcodescape/Omni-Graph](https://github.com/vaishcodescape/Omni-Graph)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* [Anthropic Claude](https://anthropic.com) -- LLM-powered extraction and RAG agent
* [Voyage AI](https://www.voyageai.com/) -- Semantic embeddings
* [pgvector](https://github.com/pgvector/pgvector) -- Vector similarity search in PostgreSQL
* [FastAPI](https://fastapi.tiangolo.com) -- REST API framework
* [Model Context Protocol](https://modelcontextprotocol.io) -- Claude Desktop integration
* [pdfminer.six](https://github.com/pdfminer/pdfminer.six) -- PDF text extraction
* [Img Shields](https://shields.io) -- README badges

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/vaishcodescape/Omni-Graph.svg?style=for-the-badge
[contributors-url]: https://github.com/vaishcodescape/Omni-Graph/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/vaishcodescape/Omni-Graph.svg?style=for-the-badge
[forks-url]: https://github.com/vaishcodescape/Omni-Graph/network/members
[stars-shield]: https://img.shields.io/github/stars/vaishcodescape/Omni-Graph.svg?style=for-the-badge
[stars-url]: https://github.com/vaishcodescape/Omni-Graph/stargazers
[issues-shield]: https://img.shields.io/github/issues/vaishcodescape/Omni-Graph.svg?style=for-the-badge
[issues-url]: https://github.com/vaishcodescape/Omni-Graph/issues
[license-shield]: https://img.shields.io/github/license/vaishcodescape/Omni-Graph.svg?style=for-the-badge
[license-url]: https://github.com/vaishcodescape/Omni-Graph/blob/main/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/adityavaish
[Python-shield]: https://img.shields.io/badge/Python_3.11-14191f?style=for-the-badge&logo=python&logoColor=3776AB
[Python-url]: https://www.python.org/
[PostgreSQL-shield]: https://img.shields.io/badge/PostgreSQL_16-14191f?style=for-the-badge&logo=postgresql&logoColor=4169E1
[PostgreSQL-url]: https://www.postgresql.org/
[pgvector-shield]: https://img.shields.io/badge/pgvector-14191f?style=for-the-badge&logo=postgresql&logoColor=6366F1
[pgvector-url]: https://github.com/pgvector/pgvector
[FastAPI-shield]: https://img.shields.io/badge/FastAPI-14191f?style=for-the-badge&logo=fastapi&logoColor=009688
[FastAPI-url]: https://fastapi.tiangolo.com/
[Docker-shield]: https://img.shields.io/badge/Docker-14191f?style=for-the-badge&logo=docker&logoColor=2496ED
[Docker-url]: https://docs.docker.com/compose/
[Anthropic-shield]: https://img.shields.io/badge/Claude_AI-14191f?style=for-the-badge&logo=anthropic&logoColor=D4A574
[Anthropic-url]: https://www.anthropic.com/
[VoyageAI-shield]: https://img.shields.io/badge/Voyage_AI-14191f?style=for-the-badge&logo=voyager&logoColor=A78BFA
[VoyageAI-url]: https://www.voyageai.com/
[MCP-shield]: https://img.shields.io/badge/Model_Context_Protocol-14191f?style=for-the-badge&logo=anthropic&logoColor=8B5CF6
[MCP-url]: https://modelcontextprotocol.io/
