"""
OmniGraph Console — Codex-style prompt REPL.

Type a natural-language question to query the AI agent, or use a
slash command for direct data operations.

Slash commands
--------------
  /search  <query> [--strategy hybrid|semantic|fulltext|graph] [--limit N]
  /entity  <name|id> [--depth N]
  /path    <entity1> <entity2> [--depth N]
  /docs    [--type <source_type>] [--limit N]
  /stats
  /audit   [--days N] [--limit N]
  /concepts <topic>
  /experts  <topic> [--limit N]
  /model   [<model-id>]
  /clear
  /help | /?
  /exit | /quit
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # type: ignore[import-untyped]

_PROJECT_ENV = _PROJECT_ROOT / ".env"
load_dotenv(_PROJECT_ENV)
load_dotenv(find_dotenv(usecwd=True))

from omnigraph.access_control_audit import AccessControlManager
from omnigraph.agentic_rag import get_anthropic_agent
from omnigraph.config import settings
from omnigraph.graph_builder import KnowledgeGraphBuilder
from omnigraph.ingestion_pipeline import DatabaseConnection
from omnigraph.semantic_query_engine import SemanticQueryEngine

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("omnigraph.console")

# ── readline (optional) ───────────────────────────────────────────────────────
try:
    import readline
    readline.set_history_length(500)
except ImportError:
    pass

# ── ANSI colours ──────────────────────────────────────────────────────────────
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── Logo ──────────────────────────────────────────────────────────────────────
LOGO = f"""{CYAN}
    ___                  _  ____                 _
   / _ \\_ __ ___  _ __ (_)/ ___|_ __ __ _ _ __ | |__
  | | | | '_ ` _ \\| '_ \\| | |  _| '__/ _` | '_ \\| '_ \\
  | |_| | | | | | | | | | | |_| | | | (_| | |_) | | | |
   \\___/|_| |_| |_|_| |_|_|\\____|_|  \\__,_| .__/|_| |_|
                                            |_|
{RESET}"""

_HELP_TEXT = f"""
  {BOLD}Slash commands{RESET}

  {CYAN}/search{RESET}  <query> [{DIM}--strategy hybrid|semantic|fulltext|graph{RESET}] [{DIM}--limit N{RESET}]
  {CYAN}/entity{RESET}  <name|id> [{DIM}--depth N{RESET}]
  {CYAN}/path{RESET}    <entity1> <entity2> [{DIM}--depth N{RESET}]
  {CYAN}/docs{RESET}    [{DIM}--type report|email|...{RESET}] [{DIM}--limit N{RESET}]
  {CYAN}/stats{RESET}
  {CYAN}/audit{RESET}   [{DIM}--days N{RESET}] [{DIM}--limit N{RESET}]
  {CYAN}/concepts{RESET} <topic>
  {CYAN}/experts{RESET}  <topic> [{DIM}--limit N{RESET}]
  {CYAN}/model{RESET}   [{DIM}<model-id>{RESET}]    show or switch AI model
  {CYAN}/clear{RESET}                  clear screen
  {CYAN}/help{RESET} | {CYAN}/?{RESET}             show this help
  {CYAN}/exit{RESET} | {CYAN}/quit{RESET}           exit

  {DIM}Or just type a question — the AI agent will answer it.{RESET}
"""


# ── Table renderer ────────────────────────────────────────────────────────────

def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


def print_table(headers: list, rows: list, widths: Optional[list] = None) -> None:
    if not rows:
        print(f"  {DIM}(no results){RESET}")
        return
    widths = widths or [
        min(
            max(len(str(h)), max((len(str(r[i])) for r in rows if i < len(r)), default=0)) + 2,
            50,
        )
        for i, h in enumerate(headers)
    ]
    header_line = "".join(
        f"{BOLD}{str(h).ljust(w)}{RESET}" for h, w in zip(headers, widths)
    )
    print(f"  {header_line}")
    print(f"  {DIM}{''.join('─' * w for w in widths)}{RESET}")
    for row in rows:
        cells = [str(row[i] if i < len(row) else "").ljust(w)[:w] for i, w in enumerate(widths)]
        print(f"  {''.join(cells)}")


# ── Console class ─────────────────────────────────────────────────────────────

class OmniGraphConsole:

    _DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self) -> None:
        self.db: Optional[DatabaseConnection] = None
        self.graph_builder: Optional[KnowledgeGraphBuilder] = None
        self.query_engine: Optional[SemanticQueryEngine] = None
        self.access_manager: Optional[AccessControlManager] = None
        self.agent = None
        self.current_user_id: Optional[int] = None
        self.current_username: Optional[str] = None
        self._agent_model: str = self._DEFAULT_MODEL

    # ── Startup ───────────────────────────────────────────────────────────

    def run(self) -> None:
        print(LOGO)
        self._connect()
        if not self._authenticate():
            self.db.disconnect()
            return
        print(_HELP_TEXT)
        self._repl()
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="logout",
            resource_type="system",
            details="Console logout",
        )
        self.db.disconnect()
        print(f"\n  {DIM}Goodbye.{RESET}\n")

    def _connect(self) -> None:
        host = settings.db_host
        print(f"  {DIM}Connecting to {host}/{settings.db_name}...{RESET} ", end="", flush=True)
        try:
            self.db = DatabaseConnection()
            self.db.connect()
            self.graph_builder = KnowledgeGraphBuilder(self.db)
            self.access_manager = AccessControlManager(self.db)
            print(f"{GREEN}✓{RESET}")
        except Exception as exc:
            print(f"{RED}✗{RESET}")
            print(f"  {RED}Connection failed: {exc}{RESET}\n")
            sys.exit(1)

    def _authenticate(self) -> bool:
        print()
        try:
            username = input(f"  Username: ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if not username:
            return False

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, full_name
                    FROM omnigraph.users
                    WHERE username = %s AND is_active = TRUE
                    """,
                    (username,),
                )
                row = cur.fetchone()
        except psycopg2.Error as exc:
            print(f"  {RED}Auth query failed: {exc}{RESET}")
            return False

        if not row:
            print(f"  {YELLOW}User '{username}' not found or inactive.{RESET}")
            return False

        self.current_user_id, full_name = row
        self.current_username = username
        self.query_engine = SemanticQueryEngine(self.db, user_id=self.current_user_id)
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="login",
            resource_type="system",
            details=f"Console login: {username}",
        )
        print(f"  {GREEN}Welcome, {full_name}.{RESET}")
        return True

    # ── REPL ─────────────────────────────────────────────────────────────

    def _repl(self) -> None:
        prompt = (
            f"\n{CYAN}omni{RESET} "
            f"{DIM}[{self.current_username}]{RESET}"
            f"{BOLD}>{RESET} "
        )
        while True:
            try:
                line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.startswith("/"):
                if self._dispatch_command(line):
                    break  # /exit or /quit returned True
            else:
                self._run_agent(line)

    def _dispatch_command(self, line: str) -> bool:
        """Dispatch a slash command. Returns True when the REPL should exit."""
        raw = line[1:]
        parts = raw.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "help":     (lambda a: self._cmd_help(),           False),
            "?":        (lambda a: self._cmd_help(),           False),
            "search":   (self._cmd_search,                     False),
            "entity":   (self._cmd_entity,                     False),
            "path":     (self._cmd_path,                       False),
            "docs":     (self._cmd_docs,                       False),
            "stats":    (lambda a: self._cmd_stats(),          False),
            "audit":    (self._cmd_audit,                      False),
            "concepts": (self._cmd_concepts,                   False),
            "experts":  (self._cmd_experts,                    False),
            "model":    (self._cmd_model,                      False),
            "clear":    (lambda a: os.system("clear || cls"),  False),
            "exit":     (lambda a: None,                       True),
            "quit":     (lambda a: None,                       True),
        }

        entry = handlers.get(cmd)
        if entry is None:
            print(f"  {YELLOW}Unknown command /{cmd}. Type /help for available commands.{RESET}")
            return False

        fn, should_exit = entry
        if not should_exit:
            try:
                fn(args)
            except Exception as exc:
                logger.exception("Command /%s failed", cmd)
                print(f"  {YELLOW}Command error: {exc}{RESET}")
        return should_exit

    # ── Agent ─────────────────────────────────────────────────────────────

    def _run_agent(self, question: str) -> None:
        if self.agent is None:
            self.agent = get_anthropic_agent(
                self.db, self.current_user_id, model=self._agent_model
            )
        if self.agent is None:
            print(
                f"\n  {YELLOW}Agent unavailable — set ANTHROPIC_API_KEY, "
                f"or use /search for keyword queries.{RESET}"
            )
            return

        print()
        text_started = False

        def on_tool_call(name: str, args: Dict) -> None:
            nonlocal text_started
            if text_started:
                # Ensure we're on a fresh line after any streamed text
                print()
                text_started = False
            arg_summary = _format_tool_args(args)
            print(f"  {DIM}⚙  {name}({arg_summary}){RESET}")

        def on_text_chunk(chunk: str) -> None:
            nonlocal text_started
            if not text_started:
                print()          # blank line before answer starts
                text_started = True
            print(chunk, end="", flush=True)

        try:
            result = self.agent.run(
                question,
                on_tool_call=on_tool_call,
                on_text_chunk=on_text_chunk,
            )
        except Exception as exc:
            logger.exception("Agent run failed")
            print(f"\n  {YELLOW}Agent error: {exc}{RESET}")
            return

        if text_started:
            print()   # trailing newline after streamed answer
        elif result.get("answer"):
            # No streaming happened (e.g. non-streaming fallback)
            print()
            for ln in result["answer"].split("\n"):
                print(f"  {ln}")

        citations = result.get("citations") or []
        if citations:
            parts = [
                f"[{c['document_id']}] {str(c.get('title', ''))[:40]}"
                for c in citations
            ]
            print(f"\n  {DIM}Sources: {' | '.join(parts)}{RESET}")

        self._audit("view", "system", details=f"Agent: {question[:80]}")

    # ── Slash command handlers ────────────────────────────────────────────

    def _cmd_help(self) -> None:
        print(_HELP_TEXT)

    def _cmd_search(self, args: str) -> None:
        ns = self._parse(
            "/search",
            args,
            [
                (["query"], {"nargs": "+", "help": "search terms"}),
                (["--strategy", "-s"], {"default": "hybrid",
                  "choices": ["hybrid", "semantic", "fulltext", "graph"]}),
                (["--limit", "-l"], {"type": int, "default": 10}),
            ],
            usage="/search <query> [--strategy hybrid|semantic|fulltext|graph] [--limit N]",
        )
        if ns is None:
            return

        query = " ".join(ns.query)
        print(f"\n  {DIM}Searching \"{query}\" ({ns.strategy})…{RESET}")

        results = self.query_engine.search(query, strategy=ns.strategy, limit=ns.limit)
        readable = self._filter_readable(results)

        if not readable:
            print(f"  {YELLOW}No results.{RESET}")
            return

        rows = [
            [i + 1, r["document_id"], r["title"][:40], r["source_type"], f"{r['score']:.3f}"]
            for i, r in enumerate(readable)
        ]
        print()
        print_table(["#", "ID", "Title", "Type", "Score"], rows, [4, 6, 42, 16, 8])
        self._audit("search", "document", details=f"Search: {query[:80]}")

    def _cmd_entity(self, args: str) -> None:
        ns = self._parse(
            "/entity",
            args,
            [
                (["name"], {"nargs": "+", "help": "entity name or numeric ID"}),
                (["--depth", "-d"], {"type": int, "default": 2}),
            ],
            usage="/entity <name|id> [--depth N]",
        )
        if ns is None:
            return

        term = " ".join(ns.name)
        entity_id = self._resolve_entity_id(term)
        if entity_id is None:
            return

        neighbors = self.graph_builder.get_entity_neighborhood(entity_id, ns.depth)
        if not neighbors:
            print(f"  {YELLOW}No neighbors found for entity #{entity_id}.{RESET}")
            return

        rows = [
            [n["entity_id"], n["name"], n["entity_type"], n["relation_type"],
             f"{n['strength']:.3f}", n["depth"]]
            for n in neighbors
        ]
        print()
        print_table(
            ["ID", "Name", "Type", "Relation", "Strength", "Depth"],
            rows,
            [6, 24, 14, 20, 10, 6],
        )

    def _cmd_path(self, args: str) -> None:
        ns = self._parse(
            "/path",
            args,
            [
                (["source"], {"help": "source entity name or ID"}),
                (["target"], {"help": "target entity name or ID"}),
                (["--depth", "-d"], {"type": int, "default": 6}),
            ],
            usage="/path <source> <target> [--depth N]",
        )
        if ns is None:
            return

        source_id = self._resolve_entity_id(ns.source)
        target_id = self._resolve_entity_id(ns.target)
        if source_id is None or target_id is None:
            return

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM omnigraph.sp_shortest_path(%s, %s, %s)",
                    (source_id, target_id, ns.depth),
                )
                rows = cur.fetchall()
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            print(f"  {YELLOW}Path lookup failed: {exc}{RESET}")
            return

        if not rows:
            print(f"  {YELLOW}No path found between #{source_id} and #{target_id}.{RESET}")
            return

        for i, row in enumerate(rows):
            entities = row[1]
            relations = row[2]
            parts = []
            for j, ent in enumerate(entities):
                parts.append(f"{BOLD}{ent}{RESET}")
                if j < len(relations):
                    parts.append(f" {DIM}──[{relations[j]}]──▶{RESET} ")
            print(f"\n  {GREEN}Path {i + 1}{RESET} {DIM}(length={row[0]}){RESET}")
            print(f"    {''.join(parts)}")

    def _cmd_docs(self, args: str) -> None:
        ns = self._parse(
            "/docs",
            args,
            [
                (["--type", "-t"], {"default": None, "metavar": "source_type"}),
                (["--limit", "-l"], {"type": int, "default": 20}),
            ],
            usage="/docs [--type report|email|...] [--limit N]",
        )
        if ns is None:
            return

        filters = ["is_archived = FALSE"]
        params: list = []
        if ns.type:
            filters.append("source_type = %s")
            params.append(ns.type)
        params.extend([ns.limit])
        where = " AND ".join(filters)

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT document_id, title, source_type, sensitivity_level,
                           TO_CHAR(created_at, 'YYYY-MM-DD') AS created_at
                    FROM omnigraph.documents
                    WHERE {where}
                    ORDER BY document_id DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows_raw = cur.fetchall()
        except psycopg2.Error as exc:
            print(f"  {YELLOW}Query failed: {exc}{RESET}")
            return

        rows = [[r[0], r[1][:40], r[2], r[3], r[4]] for r in rows_raw]
        print()
        print_table(
            ["ID", "Title", "Type", "Sensitivity", "Created"],
            rows,
            [6, 42, 16, 14, 12],
        )

    def _cmd_stats(self) -> None:
        stats = self.graph_builder.get_graph_stats()
        overview = [
            ["Documents",      stats.get("total_documents", 0)],
            ["Entities",       stats.get("total_entities", 0)],
            ["Relations",      stats.get("total_relations", 0)],
            ["Concepts",       stats.get("total_concepts", 0)],
            ["Taxonomy nodes", stats.get("total_taxonomy_nodes", 0)],
        ]
        print()
        print_table(["Metric", "Count"], overview, [20, 10])

        by_type = stats.get("entities_by_type", {})
        if by_type:
            print()
            rows = [[k, v] for k, v in sorted(by_type.items(), key=lambda x: -x[1])]
            print_table(["Entity type", "Count"], rows, [24, 10])

        self._audit("view", "system", details="Viewed graph statistics")

    def _cmd_audit(self, args: str) -> None:
        ns = self._parse(
            "/audit",
            args,
            [
                (["--days", "-d"], {"type": int, "default": 7}),
                (["--limit", "-l"], {"type": int, "default": 25}),
            ],
            usage="/audit [--days N] [--limit N]",
        )
        if ns is None:
            return

        entries = self.access_manager.get_audit_trail(days=ns.days, limit=ns.limit)
        if not entries:
            print(f"\n  {DIM}No audit entries in the last {ns.days} days.{RESET}")
            return

        rows = [
            [
                str(e["timestamp"])[:16],
                str(e.get("user", ""))[:16],
                e.get("action", ""),
                e.get("resource_type", ""),
                str(e.get("resource_id", "") or ""),
                str(e.get("details", "") or "")[:32],
            ]
            for e in entries
        ]
        print()
        print_table(
            ["Time", "User", "Action", "Resource", "ID", "Details"],
            rows,
            [17, 18, 14, 12, 5, 34],
        )
        self._audit("view", "system", details=f"Viewed audit trail (last {ns.days}d)")

    def _cmd_concepts(self, args: str) -> None:
        topic = args.strip()
        if not topic:
            print(f"  {DIM}Usage: /concepts <topic>{RESET}")
            return

        related = self.query_engine.find_related_concepts(topic)
        if not related:
            print(f"  {YELLOW}No related concepts found for '{topic}'.{RESET}")
            return

        rows = [
            [c["name"], c["domain"], c["relationship_types"],
             f"{c['connection_strength']:.3f}"]
            for c in related[:20]
        ]
        print()
        print_table(["Concept", "Domain", "Relation", "Strength"], rows, [30, 16, 25, 10])

    def _cmd_experts(self, args: str) -> None:
        ns = self._parse(
            "/experts",
            args,
            [
                (["topic"], {"nargs": "+"}),
                (["--limit", "-l"], {"type": int, "default": 10}),
            ],
            usage="/experts <topic> [--limit N]",
        )
        if ns is None:
            return

        topic = " ".join(ns.topic)
        experts = self.query_engine.find_experts(topic, limit=ns.limit)
        if not experts:
            print(f"  {YELLOW}No experts found for '{topic}'.{RESET}")
            return

        rows = [
            [e["full_name"], e.get("department", ""), f"{e.get('expertise_score', 0):.2f}"]
            for e in experts
        ]
        print()
        print_table(["Name", "Department", "Score"], rows, [28, 24, 8])

    def _cmd_model(self, args: str) -> None:
        model = args.strip()
        if not model:
            current = self.agent.model if self.agent else self._agent_model
            print(f"  Current model: {CYAN}{current}{RESET}")
            print(f"  {DIM}Usage: /model <model-id>  "
                  f"(e.g. claude-sonnet-4-6, claude-opus-4-7){RESET}")
            return
        self._agent_model = model
        self.agent = None   # force re-init on next question
        print(f"  {GREEN}Model set to {model}.{RESET}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _parse(
        self,
        prog: str,
        args: str,
        spec: list,
        usage: str = "",
    ) -> Optional[argparse.Namespace]:
        """Build an ArgumentParser from spec, parse args, return Namespace or None."""
        parser = argparse.ArgumentParser(
            prog=prog, add_help=False, exit_on_error=False
        )
        for flags, kwargs in spec:
            parser.add_argument(*flags, **kwargs)
        try:
            tokens = shlex.split(args) if args.strip() else []
            return parser.parse_args(tokens)
        except (argparse.ArgumentError, SystemExit):
            if usage:
                print(f"  {DIM}Usage: {usage}{RESET}")
            return None

    def _resolve_entity_id(self, value: str) -> Optional[int]:
        value = value.strip()
        if not value:
            print(f"  {YELLOW}No entity specified.{RESET}")
            return None
        if value.isdigit():
            return int(value)

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_id, name, entity_type, confidence,
                           (SELECT COUNT(*) FROM omnigraph.document_entities de
                            WHERE de.entity_id = e.entity_id) AS doc_count
                    FROM omnigraph.entities e
                    WHERE LOWER(e.name) = LOWER(%s) OR e.name ILIKE %s
                    ORDER BY CASE WHEN LOWER(e.name) = LOWER(%s) THEN 0 ELSE 1 END,
                             doc_count DESC
                    LIMIT 10
                    """,
                    (value, f"%{value}%", value),
                )
                matches = [
                    dict(zip(["entity_id", "name", "entity_type", "confidence", "doc_count"], r))
                    for r in cur.fetchall()
                ]
        except psycopg2.Error as exc:
            print(f"  {YELLOW}Entity lookup error: {exc}{RESET}")
            return None

        if not matches:
            print(f"  {YELLOW}No entity found for '{value}'.{RESET}")
            return None

        exact = [m for m in matches if m["name"].lower() == value.lower()]
        if len(exact) == 1:
            return exact[0]["entity_id"]

        print(f"\n  {DIM}Multiple matches for '{value}':{RESET}")
        rows = [
            [m["entity_id"], m["name"][:32], m["entity_type"],
             f"{m['confidence']:.3f}", m["doc_count"]]
            for m in matches
        ]
        print_table(["ID", "Name", "Type", "Conf", "Docs"], rows, [6, 34, 16, 6, 6])
        try:
            raw = input(f"  Entity ID to use: ").strip()
            return int(raw) if raw.isdigit() else None
        except (EOFError, ValueError):
            return None

    def _filter_readable(self, rows: List[Dict]) -> List[Dict]:
        return [
            row for row in rows
            if row.get("document_id") is not None
            and self.access_manager.check_access(
                self.current_user_id, "document", row["document_id"], "read"
            )
        ]

    def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        details: str = "",
    ) -> None:
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )


# ── Tool-arg formatter ────────────────────────────────────────────────────────

def _format_tool_args(args: Dict) -> str:
    parts = []
    for k, v in args.items():
        s = repr(v)
        parts.append(f"{k}={s[:40]}{'…' if len(s) > 40 else ''}")
    return ", ".join(parts)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console = OmniGraphConsole()
    try:
        console.run()
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Interrupted. Goodbye.{RESET}\n")
    except Exception as exc:
        print(f"\n  {RED}Fatal error: {exc}{RESET}")
        logger.exception("Fatal error in console application")
        sys.exit(1)
