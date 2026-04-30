<div align="center">

# OmniGraph

### Enterprise Knowledge Graph & Agentic RAG System

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D4A574?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**Ingest documents. Extract knowledge graphs. Query with AI agents.**

OmniGraph ingests organizational documents, extracts entities, concepts, and relationships into a queryable graph, and exposes retrieval through a hybrid search engine (full-text + vector + graph traversal) fronted by an Anthropic tool-use agent. Built around production concerns: RBAC, sensitivity tiers, audit trails, versioning, and deterministic deduplication.

<br/>

<img src="./database-schema.jpeg" alt="OmniGraph database schema ER diagram" width="800" />

</div>

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
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | Core application logic |
| **Database** | PostgreSQL 14+ | Relational storage, FTS (`tsvector` + GIN indexes) |
| **Vector Store** | pgvector (1024-dim, cosine) | Semantic similarity search |
| **Embeddings** | Voyage AI (`voyage-3`) | Document & entity embedding generation |
| **LLM Agent** | Anthropic Claude (tool-use + streaming) | Agentic RAG with 5 retrieval tools |
| **DB Driver** | psycopg2 | PostgreSQL wire protocol |
| **Config** | python-dotenv | Environment variable management |
| **Interface** | ANSI-rendered terminal console | Interactive TUI with 3 functional menus |

---

## Key Features

- **Hybrid Retrieval Engine** — Postgres full-text search (`tsvector` + GIN), 1024-dim Voyage AI vector similarity, and graph traversal unified behind a single weighted ranker
- **Agentic RAG** — Claude agent with a native tool-use loop exposing five RBAC-gated retrieval tools (`hybrid_search`, `find_experts`, `get_entity_documents`, `find_related_concepts`, `get_document_content`)
- **Relational Knowledge Graph** — 19-table PostgreSQL schema modeling documents, entities, concepts, relations, taxonomies, and user/role access policies
- **Deterministic Ingestion** — Text normalization -> SHA-256 deduplication -> versioned writes -> async embedding with UPSERT semantics
- **Enterprise Security Model** — Role-based access control with per-row sensitivity levels (`public` / `internal` / `confidential` / `restricted`); every query is filtered and logged
- **Database-First Design** — 6 stored procedures and 5 triggers enforce invariants (FTS refresh, timestamping, audit emission) in SQL rather than application code

---

## Architecture

```text
                ┌──────────────────────────────────────────────┐
                │            OmniGraph Console (TUI)           │
                └──────────────────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
┌───────────────┐          ┌──────────────────┐          ┌────────────────┐
│   Ingestion   │          │  Agentic RAG     │          │  Admin / Audit │
│   Pipeline    │          │  (Claude agent)  │          │                │
└───────┬───────┘          └─────────┬────────┘          └────────┬───────┘
        │                            │                            │
        ▼                            ▼                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│             Semantic Query Engine  +  Access Control Layer           │
│         (Full-Text  │  Vector Similarity  │  Graph Traversal)        │
└──────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                 PostgreSQL  —  schema: omnigraph                     │
│   documents · entities · concepts · relations · embeddings · roles   │
│   access_policies · taxonomy · audit_logs · query_logs · + more      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```text
raw text
  → normalize (strip control chars, collapse whitespace)
  → SHA-256 content hash → dedupe probe
      ├─ hit  → insert new row in document_versions
      └─ miss → insert into documents (FTS tsvector trigger fires)
              → Voyage AI embed → upsert into embeddings (pgvector)
              → extract:
                  ├─ keyword / regex NER  → entities + document_entities
                  ├─ concept dict scan    → concepts + document_concepts
                  └─ regex relation mine  → relations (entity → entity edges)
```

Every stage is idempotent: hash-based dedup on write, `ON CONFLICT` upserts on graph edges, and stable embedding keys `(source_type, source_id, model_name)`.

---

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ with [`pgvector`](https://github.com/pgvector/pgvector) extension
- [Voyage AI](https://www.voyageai.com/) API key
- [Anthropic](https://console.anthropic.com/) API key

### Installation

```bash
# Clone the repository
git clone https://github.com/vaishcodescape/Omni-Graph.git
cd Omni-Graph

# Install Python dependencies
pip install -r requirements.txt

# Initialize the database
createdb omnigraph
psql -d omnigraph -f sql/schema.sql
psql -d omnigraph -f sql/sample_data.sql
psql -d omnigraph -f sql/procedures_triggers.sql

# Set environment variables
export VOYAGE_API_KEY=your_voyage_key
export ANTHROPIC_API_KEY=your_anthropic_key
export OMNIGRAPH_DB_USER=postgres
export OMNIGRAPH_DB_PASSWORD=postgres

# Launch
python exec.py
```

> **Note:** Initialization order matters: `schema.sql` -> `sample_data.sql` -> `procedures_triggers.sql`

---

## Programmatic Usage

```python
from omnigraph import DatabaseConnection, DocumentIngester, SemanticQueryEngine

db = DatabaseConnection(host="localhost", dbname="omnigraph")
db.connect()

# Ingest — handles normalization, dedup, embedding, and versioning
ingester = DocumentIngester(db)
doc_id = ingester.ingest_document(
    title="Container Orchestration Primer",
    source_type="technical_doc",
    content="Kubernetes orchestrates Docker containers across clusters...",
    uploaded_by=1,
    sensitivity_level="internal",
)

# Retrieve — hybrid strategy, RBAC-filtered
engine = SemanticQueryEngine(db, user_id=1)
results = engine.search("container orchestration", strategy="hybrid", limit=5)
```

---

## Project Structure

```text
Omni-Graph/
├── exec.py                              # Entrypoint
├── requirements.txt
├── database-schema.jpeg                 # ER diagram
├── sql/
│   ├── schema.sql                       # 19 tables, constraints, indexes
│   ├── sample_data.sql                  # Seed roles / users / documents
│   ├── procedures_triggers.sql          # 6 procs + 5 triggers
│   ├── retrieval.sql                    # Advanced retrieval queries
│   └── queries.sql                      # Recursive CTEs, window functions, FTS
└── omnigraph/
    ├── __init__.py
    ├── ingestion_pipeline.py            # Normalization, SHA-256 dedup, versioning
    ├── entity_relation_extractor.py     # Pattern-based NER, concept extraction
    ├── graph_builder.py                 # Entity/relation CRUD, taxonomy trees
    ├── semantic_query_engine.py         # Full-text, vector, graph, hybrid search
    ├── access_control_audit.py          # RBAC enforcement, audit logging
    ├── agentic_rag.py                   # Claude tool-use agent orchestration
    ├── embedder.py                      # Voyage AI client wrapper
    └── console_app.py                   # ANSI terminal UI
```

---

## Database Schema — 19 Tables

All objects live in schema `omnigraph`. Full DDL in [`sql/schema.sql`](sql/schema.sql).

**Identity & Access:** `roles` · `users` · `user_roles` · `access_policies`
**Content:** `documents` · `document_versions` · `taxonomy` · `tags` · `document_tags`
**Knowledge Graph:** `entities` · `relations` · `concepts` · `concept_hierarchy` · `entity_concepts` · `document_entities` · `document_concepts`
**Semantic Layer:** `embeddings` (vector storage indexed by `source_type` + `source_id`)
**Observability:** `query_logs` · `audit_logs`

### Design Decisions

| Decision | Rationale |
| :--- | :--- |
| **Polymorphic embeddings** | One `embeddings` table spans documents, entities, and concepts via `(source_type, source_id)` — unified semantic search across all graph nodes |
| **Directed relations** | `relations(source_entity_id, target_entity_id, relation_type, strength, source_document_id)` preserves provenance back to the source document |
| **Row-level sensitivity** | `documents.sensitivity_level` is authoritative; every retrieval re-checks `access_policies` at read time |

---

## Retrieval Strategies

| Strategy | Mechanism | Best For |
| :--- | :--- | :--- |
| `fulltext` | PostgreSQL `tsvector` / `tsquery`, GIN-indexed | Exact keyword matches, acronyms |
| `semantic` | Voyage `voyage-3` query embedding -> pgvector nearest neighbor | Natural-language intent, paraphrases |
| `graph` | Traverse `document_entities -> entities -> relations -> entities -> document_entities` | "What else is connected to X?" |
| `hybrid` | All three, blended with weights `{fulltext: 1.0, semantic: 1.2, graph: 0.8}` | Most production queries (default) |

Every result is post-filtered through `AccessControlManager.check_access` before returning to the caller or agent.

---

## Console Capabilities

| Menu | Features |
| :--- | :--- |
| **Search & Discover** | Ask (Agent), Full-text search, Hybrid/semantic search, Find experts, Explore related concepts, Entity-based document lookup, Entity neighborhood view, Entity path lookup |
| **Manage Documents** | Add, Update metadata, Tag, View detail, List recent, Run extraction |
| **Administration** | Graph stats, Structure views, Audit trail, Sensitive-access report, Query analytics, Role assignment/revocation, Read-only SQL sandbox |

### Sample Agent Queries

```text
What documents explain Kubernetes deployment?
Who are the experts on Deep Learning?
What concepts are related to Machine Learning?
Which documents mention PostgreSQL?
```

---

## Engineering Highlights

| Practice | Implementation |
| :--- | :--- |
| **Separation of Concerns** | Retrieval, access control, and orchestration are distinct modules; the agent composes them |
| **SQL-as-Contract** | Invariants (timestamping, FTS maintenance, audit emission) enforced by triggers and stored procedures |
| **Idempotent Writes** | Hash dedup, `ON CONFLICT` upserts, and stable embedding keys make the pipeline safe to re-run |
| **Graceful Degradation** | Embedding failures are logged but don't roll back document writes; FTS and graph retrieval remain functional |
| **Provenance Tracking** | Every extracted relation stores `source_document_id`, making the graph auditable |
| **Observability by Default** | `query_logs` captures latency and result counts; `audit_logs` captures every sensitive access |

---

## Configuration

| Environment Variable | Purpose | Required |
| :--- | :--- | :---: |
| `OMNIGRAPH_DB_USER` | PostgreSQL user (default: `postgres`) | No |
| `OMNIGRAPH_DB_PASSWORD` | PostgreSQL password | Yes |
| `VOYAGE_API_KEY` | Voyage AI — embedding + semantic search | Yes |
| `ANTHROPIC_API_KEY` | Anthropic Claude — agentic RAG loop | Yes |

---

## Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/your-feature`)
3. **Commit** your changes (`git commit -m 'Add your feature'`)
4. **Push** to the branch (`git push origin feature/your-feature`)
5. **Open** a Pull Request

### Areas for Contribution

- Additional NER patterns and entity extraction strategies
- New retrieval strategies or ranking algorithms
- Frontend/web UI for the console
- Docker/Docker Compose setup for easier deployment
- Test coverage improvements
- Documentation and examples

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
