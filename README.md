<div align="center">

<img src="logo.png" alt="Data-Spear logo" width="140" />

### Data-Spear

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python_3.14-14191f?logo=python&logoColor=3776AB" alt="Python" /></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-14191f?logo=postgresql&logoColor=4169E1" alt="PostgreSQL" /></a>
  <a href="https://www.pinecone.io/"><img src="https://img.shields.io/badge/Pinecone-14191f?logo=googledataflow&logoColor=6366F1" alt="Pinecone" /></a>
  <a href="https://www.anthropic.com/"><img src="https://img.shields.io/badge/Claude_AI-14191f?logo=anthropic&logoColor=D4A574" alt="Claude AI" /></a>
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/Rust_TUI-14191f?logo=rust&logoColor=CE412B" alt="Rust TUI" /></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-14191f?logo=docker&logoColor=2496ED" alt="Docker" /></a>
</p>

An autonomous SQL agent for PostgreSQL, in your terminal.

</div>

---

Data-Spear answers questions about your database by **acting like an analyst, not a search box**: it plans, inspects schemas, runs live SQL, verifies its own results, and cites every claim. Retrieval (Pinecone) supplies context; the agent (Claude) treats the live database as the source of truth.

```text
Rust TUI ──HTTP/SSE──▶ FastAPI ──▶ Agent loop (Claude)
(ratatui)              (Python)      ├─ inspect_schema / explain / run_query
                                     ├─ begin / commit / rollback
                                     └─ Pinecone retrieval (per-DB namespace)
```

#### Features

- **Live agent trace** — every tool call streams into the TUI as it happens (`✓ run_query SELECT … → 12 rows`) and stays as an audit log.
- **Tiered SQL safety, enforced server-side** — reads run freely; bounded writes must be transaction-wrapped; destructive/DDL statements (`DROP`, `ALTER`, unbounded `UPDATE`/`DELETE`) are rejected unless you authorize the request with a `!` prefix.
- **Connect at startup** — point the TUI at any local or hosted Postgres (Neon, Supabase, RDS, …); credentials are validated before the chat opens.
- **Isolated retrieval** — vectors are namespaced per connected database, so context never leaks across databases.
- **Guardrails** — per-statement timeout, automatic rollback of unwrapped writes, optional bearer-token auth on the API.

#### Quickstart

Requirements: Python 3.14+, Rust toolchain, a PostgreSQL database, [Pinecone](https://www.pinecone.io/) and [Anthropic](https://console.anthropic.com/) API keys.

**1. Server**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env          # fill in PINECONE_API_KEY and ANTHROPIC_API_KEY

.venv/bin/uvicorn data_spear.api.main:app --port 8000
```

**2. TUI** (separate terminal)

```bash
cd data-spear-tui
cargo run --release
```

Enter your database credentials on the connection screen (defaults target `localhost:5432/postgres`), then ask away.

**3. Optional: ingest context**

Declare which tables to index in `SOURCES` ([data_spear/config.py](data_spear/config.py)), then run `/ingest` from the TUI. The agent works without ingestion — it just leans on live queries instead of retrieval.

#### TUI reference

| Input | Action |
| --- | --- |
| `Enter` | send prompt |
| `! <prompt>` | send with destructive-SQL authorization (Tier 2) |
| `/help` `/clear` `/trace` `/ingest` | commands |
| `↑` / `↓` | prompt history |
| `PgUp` / `PgDn` | scroll transcript |
| `Ctrl+T` / `Ctrl+L` | toggle trace / clear conversation |
| `Esc` | clear input, quit when empty |

#### API

| Endpoint | Purpose |
| --- | --- |
| `POST /connect` | validate credentials, set the active database |
| `POST /query` | one-shot answer with sources |
| `POST /query/stream` | answer as Server-Sent Events (agent progress + final) |
| `POST /ingest` | index configured `SOURCES` into Pinecone |
| `GET /healthz` | liveness |

Set `API_TOKEN` in `.env` to require `Authorization: Bearer …` on all endpoints (the TUI sends it from `DATA_SPEAR_API_TOKEN`).

### Database Schema Example for Data_Spear
<div>
<img src="./database-schema.jpeg" alt="demo-schema" width="860" />
</div>

#### Configuration

All settings come from `.env` / environment (see [data_spear/config.py](data_spear/config.py)):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PG_DSN` | local postgres | fallback DSN when `/connect` isn't used |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | — / `data-spear` | vector store |
| `ANTHROPIC_API_KEY` / `ANSWER_MODEL` | — / `claude-opus-4-8` | agent model |
| `TOP_K` | `6` | retrieved chunks per query |
| `API_TOKEN` | empty (off) | bearer-token auth |
| `STATEMENT_TIMEOUT_MS` | `30000` | cap on each SQL statement the agent runs |

The TUI reads `DATA_SPEAR_API` (default `http://localhost:8000`) and `DATA_SPEAR_API_TOKEN`.

#### Docker

```bash
docker build -t data-spear .
docker run --rm -p 8000:8000 --env-file .env data-spear
```

> Keep `UVICORN_WORKERS=1` — the active database connection is per-process state.

#### License

[MIT](LICENSE)
