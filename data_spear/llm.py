#Config for LLM
from __future__ import annotations

import json
import re
from typing import Any, Iterator, cast

import psycopg2
import psycopg2.extras
from anthropic import Anthropic
from anthropic.types import TextBlock, ToolUseBlock

from config import settings
from db import active_dsn


SYSTEM_PROMPT = """\
You are Data-Spear, an autonomous data agent over a PostgreSQL database. You receive a task and, on turns where retrieval ran, `<context>` — chunks from a vector index tagged `[table:id]` or `[table:id:chunk]` with similarity scores. You work in a loop — plan, act, observe, adapt — issuing as many tool calls across as many steps as the task requires, until it is complete or a stop condition fires.

Cite every claim: `[customers:42]` for a retrieved chunk, `[live:run_query#N]` for evidence fetched via a tool.

## Agent loop

1. **Plan.** Decompose the task into the fewest verifiable steps. Identify which steps read and which mutate; mark any Tier 2 step as a confirmation gate *before* executing anything. State the assumptions you're operating under.
2. **Ground.** Treat retrieved context as a snapshot and the live database as truth. Answer from chunks alone only when they fully cover the question; otherwise escalate (criteria below).
3. **Act.** Execute the next step with the narrowest call that advances it. Independent reads (inspecting several tables, probing unrelated counts) may run in parallel; dependent steps run in sequence. `inspect_schema` any table whose structure isn't already evidenced before touching it.
4. **Observe and adapt.** After every result, update the plan: facts confirmed, assumptions invalidated, steps now unnecessary or newly required. Never execute a step whose premise the evidence has broken.
5. **Verify, then finish.** Before the final answer: every claim carries a citation, every mutation's actual row count matched its estimate, and nothing asserted is hypothesized-but-unchecked.

## Stop conditions and budgets

Stop and report — don't spin — when any of these hits:

- Task complete and verified.
- A Tier 2 gate needs user confirmation.
- A permission error blocks the remaining path.
- Evidence shows the task is impossible or ill-posed as stated.
- Soft budget exceeded (~15 tool calls per task): pause, summarize what's done and what remains, propose how to proceed.

Never retry an identical failing statement more than once. Do exactly what was asked: note adjacent problems you discover (missing index, suspect data) in the final report, but don't fix them unrequested.

## Escalate from retrieval to live tools when

- The question needs aggregates, counts, or current values.
- A claim hinges on a column or relationship absent from the chunks.
- Chunks are missing, contradictory, or low-similarity.
- The task mutates data.
- A citation would otherwise be unverified — confirm with a narrow `SELECT` before asserting.

If retrieval returned `(no context retrieved)`, say so and proceed via tools.

## Operation tiers (every statement you issue)

- **Tier 0 — read-only.** `SELECT`, `EXPLAIN`, catalog queries. Execute directly; cap exploratory reads with `LIMIT`.
- **Tier 1 — bounded mutation.** `INSERT`; `UPDATE`/`DELETE` with `WHERE`. Estimate affected rows via `SELECT COUNT(*)`, `begin`, execute, `commit` only if actual matches estimate — otherwise `rollback` and report the discrepancy.
- **Tier 2 — destructive, structural, or unbounded.** `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, migrations, `UPDATE`/`DELETE` without `WHERE`, bulk ops, constraint/index/grant changes. Hard pause: present the exact statement(s), scope, and reversibility, then stop and await explicit confirmation. Batch related Tier 2 statements into a single confirmation when they serve one stated intent. Confirmation covers only the statements shown — anything that changes must be re-confirmed. The server independently rejects Tier 2 statements unless the user pre-authorized this request (a `!` prefix on their message); when blocked, present the exact statements and tell the user to re-send the request prefixed with `!` if they approve.

If a request maps to a higher tier than the user seems to expect (their `UPDATE` omits `WHERE`), flag it before doing anything. If you can't confirm prod vs. non-prod and the op is Tier 2, that is itself a stop condition.

## Error policy (classify, then act)

Report the verbatim code and message, then:

- **Transient** (deadlock, timeout, connection): retry once after backoff. Second failure → stop that branch; continue independent ones.
- **Permission:** never retry. Report the exact missing grant; continue any steps it doesn't block.
- **Constraint:** never bypass or disable checks. Surface the violated constraint; propose a compliant alternative if the intent permits one.
- **Query-logic** (syntax, unknown identifier, type mismatch): re-inspect the schema, fix once, retry once. Still failing → report verbatim and stop that branch.

## State and context hygiene

- Maintain a working ledger across steps: verified facts (with source), open questions, steps done and pending. In multi-turn tasks, restate the ledger compactly rather than re-deriving it from scratch.
- Never pull large result sets into reasoning or answers. Aggregate in SQL, `LIMIT` samples (≤20 rows) when eyeballing data, and summarize the rest with counts.
- Keep snapshot facts `[table:id]` and live facts `[live:...]` distinct; anything time-sensitive must be live.

## Ambiguity

- Ambiguous on a low-stakes axis (output shape, two equivalent reads of the question): proceed with the most reasonable interpretation and state the assumption in the final answer.
- Ambiguous on blast radius (which rows, which environment, destructive scope): stop and ask one targeted question before acting.

## Query quality

- No `SELECT *` outside ad-hoc inspection.
- Predicates and join keys must be index-backed; match types on both sides — implicit casts kill index usage. `explain` anything likely to scan a large table before running it.
- Set-based over row-by-row. Batch large mutations; flag lock and replication-lag risk.
- Keyset pagination over `OFFSET` for deep paging.
- Bound parameters for every literal. Never interpolate values into SQL.

## Hard rules

- Never run Tier 2 without explicit confirmation.
- Never `DELETE`/`UPDATE`/`TRUNCATE` a whole table when intent describes a subset.
- Never interpolate raw values into SQL.
- Never disable FK/trigger/constraint checks to make a write succeed.
- Never invent schema, row counts, or results. No silent failure — surface every error.
- Never echo secrets, credentials, PII, or full sensitive dumps unless explicitly authorized.

## Tools

- `inspect_schema` — tables, columns, types, keys, indexes.
- `explain` — query plan without executing (or on a bounded sample).
- `run_query` — execute parameterized SQL; returns rows or affected count.
- `begin` / `commit` / `rollback` — transaction control. Required around Tier 1/2 writes.

## Output

**While working** (pausing at a confirmation gate or budget): progress so far, what you're blocked on, proposed next step.

**Final:**

- **Answer** — with inline `[source:id]` citations.
- **Evidence** — which retrieved chunks vs. live queries grounded each claim (omit if trivially obvious).
- **SQL (when used)** — parameterized statements in fenced blocks, each labeled with its tier.
- **Scope (writes only)** — estimated → actual affected rows; reversibility note for Tier 2.
- **Assumptions / flags** — interpretation choices made; adjacent issues noticed but not fixed.

Keep the answer tight. Cite; don't restate the question.
"""


TOOLS: list[dict] = [
    {
        "name": "inspect_schema",
        "description": (
            "Inspect the PostgreSQL catalog. With no `table`, returns the list of tables in "
            "the given schema. With a `table`, returns its columns (name, type, nullable, "
            "default), primary key, foreign keys, and indexes. Use this BEFORE writing any "
            "query that touches a table you have not yet inspected this session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Optional table name. Omit to list tables.",
                },
                "schema": {
                    "type": "string",
                    "description": "Schema name. Defaults to 'public'.",
                    "default": "public",
                },
            },
        },
    },
    {
        "name": "explain",
        "description": (
            "Return the PostgreSQL query plan for `sql` WITHOUT executing it. "
            "Use this to validate any non-trivial read and every write before running it. "
            "Pass bound `params` for any literal values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "params": {
                    "type": "array",
                    "items": {},
                    "description": "Positional bound parameters for %s placeholders.",
                    "default": [],
                },
                "analyze": {
                    "type": "boolean",
                    "description": (
                        "If true, run EXPLAIN ANALYZE (executes the query). "
                        "Only set true on Tier 0 reads or on a SAFE bounded sample."
                    ),
                    "default": False,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "run_query",
        "description": (
            "Execute SQL with bound parameters. Returns rows for reads or affected-row count "
            "for writes. For Tier 1/2 operations, call `begin` first and `commit`/`rollback` "
            "after. Tier 2 statements require the user to have explicitly confirmed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "params": {
                    "type": "array",
                    "items": {},
                    "description": "Positional bound parameters for %s placeholders.",
                    "default": [],
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Cap on returned rows for reads. Defaults to 100.",
                    "default": 100,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "begin",
        "description": "Open an explicit transaction. Must precede any Tier 1 or Tier 2 write.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "commit",
        "description": "Commit the open transaction. Only call after verifying affected-row count.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "rollback",
        "description": "Roll back the open transaction. Call on any unexpected result or error.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


_MAX_AGENT_TURNS = 12

# Cache the system prompt (and the tools block that precedes it in the prompt
# prefix) across the loop's turns — it is identical on every call.
_CACHED_SYSTEM = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]


class LLM:
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = Anthropic(api_key=settings.anthropic_api_key)

    def answer(
        self,
        prompt: str,
        context_blocks: list[dict],
        allow_destructive: bool = False,
    ) -> str:
        final = "(no answer produced)"
        for evt in self.answer_events(prompt, context_blocks, allow_destructive):
            if evt["type"] == "final":
                final = evt["answer"]
        return final

    def _create(self, messages: list[dict], **kwargs: Any):
        return self._client.messages.create(
            model=settings.answer_model,
            max_tokens=2048,
            system=cast(Any, _CACHED_SYSTEM),
            tools=cast(Any, TOOLS),
            messages=cast(Any, messages),
            **kwargs,
        )

    def answer_events(
        self,
        prompt: str,
        context_blocks: list[dict],
        allow_destructive: bool = False,
    ) -> Iterator[dict]:
        context = _format_context(context_blocks)
        user_message = (
            f"<context>\n{context}\n</context>\n\n"
            f"<question>\n{prompt}\n</question>"
        )
        messages: list[dict] = [{"role": "user", "content": user_message}]

        session = _DBSession(allow_destructive=allow_destructive)
        try:
            for _ in range(_MAX_AGENT_TURNS):
                resp = self._create(messages)

                messages.append({"role": "assistant", "content": resp.content})
                text = "".join(
                    b.text for b in resp.content if isinstance(b, TextBlock)
                )

                if resp.stop_reason != "tool_use":
                    if resp.stop_reason == "max_tokens":
                        text += "\n\n⚠ answer truncated at the model's token limit"
                    yield {"type": "final", "answer": text}
                    return

                if text.strip():
                    yield {"type": "thinking", "text": text.strip()}

                tool_results = []
                for block in resp.content:
                    if not isinstance(block, ToolUseBlock):
                        continue
                    args = dict(block.input or {})
                    yield {
                        "type": "tool_use",
                        "name": block.name,
                        "detail": _summarize_tool_input(block.name, args),
                    }
                    result, is_error = session.dispatch(block.name, args)
                    yield {
                        "type": "tool_result",
                        "name": block.name,
                        "ok": not is_error,
                        "detail": _summarize_tool_result(result, is_error),
                    }
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                        "is_error": is_error,
                    })
                messages.append({"role": "user", "content": tool_results})

            # Budget exhausted: force a final synthesis from the evidence gathered
            # instead of discarding the whole session. Trailing text in the same
            # user message keeps roles alternating.
            messages[-1]["content"].append({
                "type": "text",
                "text": (
                    "Tool budget exhausted. Stop investigating and produce your best "
                    "final answer now from the evidence gathered so far, with "
                    "citations. List anything that remains unverified."
                ),
            })
            resp = self._create(messages, tool_choice={"type": "none"})
            text = "".join(b.text for b in resp.content if isinstance(b, TextBlock))
            yield {
                "type": "final",
                "answer": text
                or "(agent loop exhausted before producing a final answer)",
            }
        finally:
            session.close()


def _one_line(s: str, limit: int = 88) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _summarize_tool_input(name: str, args: dict) -> str:
    """Compact human-readable summary of a tool call for progress display."""
    if name == "inspect_schema":
        table = args.get("table")
        return str(table) if table else f"list tables in {args.get('schema', 'public')}"
    if name in ("run_query", "explain"):
        return _one_line(str(args.get("sql", "")))
    return ""


def _summarize_tool_result(result: Any, is_error: bool) -> str:
    if is_error:
        if isinstance(result, dict):
            return _one_line(f"{result.get('error', 'error')}: {result.get('message', '')}")
        return "error"
    if isinstance(result, dict):
        if "rows" in result:
            n = result.get("row_count", len(result["rows"]))
            extra = " (truncated)" if result.get("truncated") else ""
            return f"{n} row{'s' if n != 1 else ''}{extra}"
        if "rowcount" in result:
            base = f"{result['rowcount']} affected"
            if result.get("warning"):
                base += f" — {_one_line(str(result['warning']), 60)}"
            return base
        if "plan" in result:
            plan = result["plan"]
            return _one_line(str(plan[0])) if plan else "plan"
        if "tables" in result:
            return f"{len(result['tables'])} tables"
        if "columns" in result:
            return f"{len(result['columns'])} columns"
        if "status" in result:
            return str(result["status"])
    return ""


def _format_context(blocks: list[dict]) -> str:
    if not blocks:
        return "(no context retrieved)"
    out = []
    for b in blocks:
        out.append(f"[{b['id']}] (score={b['score']:.3f})\n{b['fields'].get('chunk_text', '')}")
    return "\n\n---\n\n".join(out)


# Conservative keyword scan for Tier 2 (destructive/structural/unbounded) SQL.
# May rarely flag a keyword inside a literal; the model can rephrase. Scanning the
# whole string also catches multi-statement payloads ("SELECT 1; DROP TABLE x").
_TIER2_RE = re.compile(
    r"\b(drop|truncate|alter|create|grant|revoke|reindex|comment\s+on)\b",
    re.IGNORECASE,
)


def _tier2_reason(sql: str) -> str | None:
    """Why `sql` is Tier 2, or None if it isn't."""
    m = _TIER2_RE.search(sql)
    if m:
        return f"{m.group(0).upper()} statement"
    head = re.match(r"\s*(update|delete)\b", sql, re.IGNORECASE)
    if head and not re.search(r"\bwhere\b", sql, re.IGNORECASE):
        return f"{head.group(1).upper()} without WHERE"
    return None


class _DBSession:
    # Holds one PG connection and an in-transaction flag across tool calls.

    def __init__(self, allow_destructive: bool = False) -> None:
        self._conn = None
        self._in_tx = False
        self._allow_destructive = allow_destructive

    def _ensure_conn(self):
        if self._conn is None:
            self._conn = psycopg2.connect(
                active_dsn(),
                connect_timeout=10,
                # Bound every statement so a runaway query can't stall the agent turn.
                options=f"-c statement_timeout={settings.statement_timeout_ms}",
            )
        return self._conn

    def _check_tier2(self, sql: str) -> None:
        if self._allow_destructive:
            return
        reason = _tier2_reason(sql)
        if reason:
            raise PermissionError(
                f"Tier 2 statement blocked by server policy ({reason}). Present the "
                "exact statement to the user in your final answer; they can authorize "
                "it by re-sending their request prefixed with '!'."
            )

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            if self._in_tx:
                self._conn.rollback()
        finally:
            self._conn.close()
            self._conn = None
            self._in_tx = False

    def dispatch(self, name: str, args: dict) -> tuple[Any, bool]:
        try:
            handler = {
                "inspect_schema": self._inspect_schema,
                "explain": self._explain,
                "run_query": self._run_query,
                "begin": self._begin,
                "commit": self._commit,
                "rollback": self._rollback,
            }.get(name)

            if handler is None:
                return ({"error": f"unknown tool: {name}"}, True)
            return (handler(**args), False)
        
        except Exception as e:
            # Mark the connection clean so subsequent tool calls aren't stuck in an
            # aborted-transaction state.
            rolled_back = False
            if self._conn is not None:
                try:
                    self._conn.rollback()
                    rolled_back = self._in_tx
                except Exception:
                    pass
                self._in_tx = False
            return (
                {
                    "error": type(e).__name__,
                    "message": str(e),
                    # Tell the model its transaction is gone, or it may keep
                    # operating as if the tx were still open.
                    "transaction_rolled_back": rolled_back,
                },
                True,
            )

    def _cursor(self):
        conn = self._ensure_conn()
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _inspect_schema(self, table: str | None = None, schema: str = "public") -> dict:
        if table is None:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name",
                    (schema,),
                )
                return {"schema": schema, "tables": [r["table_name"] for r in cur.fetchall()]}

        with self._cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (schema, table),
            )
            columns = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                " AND tc.table_schema = kcu.table_schema "
                "WHERE tc.constraint_type = 'PRIMARY KEY' "
                "  AND tc.table_schema = %s AND tc.table_name = %s "
                "ORDER BY kcu.ordinal_position",
                (schema, table),
            )
            pk = [r["column_name"] for r in cur.fetchall()]

            cur.execute(
                "SELECT kcu.column_name, ccu.table_name AS ref_table, "
                "       ccu.column_name AS ref_column "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' "
                "  AND tc.table_schema = %s AND tc.table_name = %s",
                (schema, table),
            )
            fks = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = %s",
                (schema, table),
            )
            indexes = [dict(r) for r in cur.fetchall()]

        return {
            "schema": schema,
            "table": table,
            "columns": columns,
            "primary_key": pk,
            "foreign_keys": fks,
            "indexes": indexes,
        }

    def _explain(self, sql: str, params: list | None = None, analyze: bool = False) -> dict:
        if analyze:
            # EXPLAIN ANALYZE *executes* the statement — only allow it on reads.
            if not re.match(r"\s*(select|with|table|values)\b", sql, re.IGNORECASE):
                raise PermissionError(
                    "EXPLAIN ANALYZE executes the statement; analyze=true is only "
                    "allowed for SELECT queries. Use plain explain for writes."
                )
            self._check_tier2(sql)
        prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " if analyze else "EXPLAIN "
        with self._cursor() as cur:
            cur.execute(prefix + sql, params or [])
            plan = [next(iter(r.values())) for r in cur.fetchall()]
        # EXPLAIN inside a connection that was idle starts an implicit tx — close it
        # if the model hasn't opened one explicitly.
        if not self._in_tx and self._conn is not None:
            self._conn.rollback()
        return {"plan": plan}

    def _run_query(self, sql: str, params: list | None = None, max_rows: int = 100) -> dict:
        self._check_tier2(sql)
        with self._cursor() as cur:
            cur.execute(sql, params or [])
            if cur.description is None:
                rowcount = cur.rowcount
                if not self._in_tx and self._conn is not None:
                    # Auto-commit reads/writes the model didn't wrap; safer to roll back
                    # writes that weren't preceded by `begin`. Reads have no effect.
                    self._conn.rollback()
                    return {
                        "rowcount": rowcount,
                        "warning": (
                            "No open transaction — write was rolled back. Call `begin` "
                            "before issuing Tier 1/2 writes."
                        ),
                    }
                return {"rowcount": rowcount}

            rows = cur.fetchmany(max_rows)
            truncated = cur.rowcount > max_rows if cur.rowcount >= 0 else False
            if not self._in_tx and self._conn is not None:
                self._conn.rollback()
            return {
                "columns": [d.name for d in cur.description],
                "rows": [dict(r) for r in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }

    def _begin(self) -> dict:
        if self._in_tx:
            return {"status": "already in transaction"}
        # psycopg2 opens an implicit tx on first statement; ensure clean state then mark.
        conn = self._ensure_conn()
        conn.rollback()
        self._in_tx = True
        return {"status": "transaction open"}

    def _commit(self) -> dict:
        if not self._in_tx or self._conn is None:
            return {"status": "no open transaction"}
        self._conn.commit()
        self._in_tx = False
        return {"status": "committed"}

    def _rollback(self) -> dict:
        if not self._in_tx or self._conn is None:
            return {"status": "no open transaction"}
        self._conn.rollback()
        self._in_tx = False
        return {"status": "rolled back"}
