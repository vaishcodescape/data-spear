<div align="center">

<img src="images/data-spear.png" alt="Data-Spear logo" width="140" />

# Data-Spear

<p>
  <a href="https://github.com/vaishcodescape/data-spear/actions/workflows/ci.yml"><img src="https://github.com/vaishcodescape/data-spear/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python_3.11+-14191f?logo=python&logoColor=3776AB" alt="Python" /></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-14191f?logo=postgresql&logoColor=4169E1" alt="PostgreSQL" /></a>
  <a href="https://www.anthropic.com/"><img src="https://img.shields.io/badge/Claude_AI-14191f?logo=anthropic&logoColor=D4A574" alt="Claude AI" /></a>
  <a href="https://www.gnu.org/software/bash/"><img src="https://img.shields.io/badge/Bash_CLI-14191f?logo=gnubash&logoColor=4EAA25" alt="Bash CLI" /></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-14191f?logo=docker&logoColor=2496ED" alt="Docker" /></a>
</p>

**An autonomous SQL agent for PostgreSQL, in your terminal.**

</div>

---

Data-Spear answers questions and automates your database by **acting like an analyst, not a search box**: it plans, inspects schemas, runs live SQL, verifies its own results, and cites every claim. Retrieval (Pinecone) supplies context, but the agent always treats the live database as the source of truth.

## Contents

- [Data-Spear](#data-spear)
  - [Contents](#contents)
  - [Features](#features)
  - [Architecture](#architecture)
  - [Postgres Guard Rails safety tiers](#postgres-guard-rails-safety-tiers)
  - [Quickstart](#quickstart)
  - [CLI Commands](#cli-commands)
  - [API Endpoints](#api-endpoints)
  - [Experimental schema](#experimental-schema)
  - [Configuration](#configuration)
  - [Docker](#docker)
  - [Development](#development)
  - [License](#license)

## Features

- **Live agent trace** — every tool call streams into the terminal as it happens (`✓ run_query SELECT … → 12 rows`) and stays as an audit log.
- **Tiered SQL safety, enforced server-side** — reads run freely; bounded writes must be transaction-wrapped; destructive/DDL statements are rejected unless you explicitly authorize them. See [safety tiers](#postgres-guard-rails-safety-tiers).
- **Connect at startup** — point the CLI at any local or hosted Postgres (Neon, Supabase, RDS, …); credentials are validated before the chat opens.
- **Isolated retrieval** — vectors are namespaced per connected database, so context never leaks across databases.
- **Guardrails** — per-statement timeout, automatic rollback of unwrapped writes, optional bearer-token auth on the API.

## Architecture

<div align="center">
<img src="./images/data_spear_architecture.png" alt="Data-Spear architecture" width="900" />
</div>


## Postgres Guard Rails safety tiers

| Tier | Statements | Policy |
| --- | --- | --- |
| Read | `SELECT`, `EXPLAIN`, schema inspection | Run freely |
| Bounded write | `INSERT` / `UPDATE` / `DELETE` with a `WHERE` clause | Must be wrapped in `begin` … `commit`; unwrapped writes are rolled back automatically |
| Destructive (Tier 2) | DDL (`DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, …) and `UPDATE` / `DELETE` without `WHERE` | Rejected unless the prompt is sent with a `!` prefix |

Enforcement happens server-side in the agent's tool dispatcher — the model cannot bypass it. As a hard backstop, every database session is opened **READ ONLY**; the read-write mode is lifted only inside an explicit `begin`, so any write the keyword scan misses (e.g. a data-modifying CTE) is still refused by Postgres itself. For real isolation, connect Data-Spear with a least-privilege role — in-app tiers are a guardrail, database grants are the boundary.

## Quickstart

Requirements: Python 3.11+, `curl` and `jq`, a PostgreSQL database, [Pinecone](https://www.pinecone.io/) and [Anthropic](https://console.anthropic.com/) API keys.

**1. Server**

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env          # fill in ANTHROPIC_API_KEY and PINECONE_API_KEY

./scripts/data-spear.sh serve
```

**2. CLI** (separate terminal)

```bash
./scripts/data-spear.sh chat
```

Enter your database credentials at the connection prompt (defaults target `localhost:5432/postgres`), then ask away. For scripting, skip the REPL and use one-shot commands:

```bash
./scripts/data-spear.sh connect --host db.example.com --dbname sales --user me --password secret
./scripts/data-spear.sh ask "how many orders shipped in the last 7 days?"
```

**3. Optional: ingest context**

Declare which tables to index in `SOURCES` ([data_spear/config.py](data_spear/config.py)), then run `/ingest` from the chat REPL (or `./scripts/data-spear.sh ingest`). The agent works without ingestion — it just leans on live queries instead of retrieval.

## CLI Commands

| Command | Action |
| --- | --- |
| `serve [port]` | start the API server (default port 8000) |
| `connect [--dsn URL \| --host … --dbname …]` | set the active database; interactive when run without flags |
| `ask "prompt"` | one-shot question with a live agent trace |
| `ask --destructive "prompt"` | authorize destructive SQL for this request (Tier 2) |
| `chat` | interactive REPL (`/help`, `/ingest`, `/connect`, `/quit`; `! <prompt>` authorizes Tier 2 SQL) |
| `ingest` | index configured `SOURCES` into Pinecone |
| `health` | check the API is reachable |

Set `DATA_SPEAR_API` to target a non-default API URL and `DATA_SPEAR_API_TOKEN` if the server requires a bearer token.

## API Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /connect` | validate credentials, set the active database |
| `POST /query` | one-shot answer with sources |
| `POST /query/stream` | answer as Server-Sent Events (agent progress + final) |
| `POST /ingest` | index configured `SOURCES` into Pinecone |
| `GET /healthz` | liveness |

## Experimental schema

A demo enterprise schema you can point Data-Spear at to try it out:

<div align="center">
<img src="./images/database-schema.jpeg" alt="Demo database schema" width="860" />
</div>

## Configuration

All settings come from `.env` / environment (see [data_spear/config.py](data_spear/config.py)):

```bash
# PostgreSQL
PG_DSN=postgresql://user:password@localhost:5432/database

# Pinecone
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX=data-spear

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key
ANSWER_MODEL=claude-opus-4-8
ANSWER_MAX_TOKENS=2048        # max output tokens per agent turn
MAX_AGENT_TURNS=12            # hard cap on agent-loop turns

# Retrieval
TOP_K=6

# SQL execution timeout (milliseconds)
STATEMENT_TIMEOUT_MS=30000

# API auth (optional) — when set, every endpoint except /healthz requires
# `Authorization: Bearer <token>`.
API_TOKEN=
```

## Docker

Build and run the API, then point it at your database from the CLI's `connect`:

```bash
docker build -t data-spear .
docker run --rm -p 8000:8000 --env-file .env data-spear
```

Or bring up the API alongside a throwaway Postgres with Compose:

```bash
docker compose up --build
```

The server runs a **single worker** by default: it holds one active database connection in per-process state, so `connect` and the queries that follow must reach the same worker. Only raise `UVICORN_WORKERS` if every request is independently connected.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"   # runtime deps + pytest, httpx, ruff

.venv/bin/pytest                    # run the test suite
.venv/bin/ruff check .              # lint
```

CI runs the same lint and tests on every push and pull request (Python 3.11–3.13).

## License

[MIT](LICENSE)
