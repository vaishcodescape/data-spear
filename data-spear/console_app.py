"""
OmniGraph Console — Codex-style REPL with a Rich-rendered TUI layer.

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

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle

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

# ── Theme ─────────────────────────────────────────────────────────────────────
# A single shared Console — every render goes through this so the whole app
# stays internally consistent and respects NO_COLOR / pipes automatically.
console = Console(highlight=False)

C_BRAND   = "bold cyan"
C_ACCENT  = "magenta"
C_DIM     = "grey50"
C_OK      = "bold green"
C_WARN    = "yellow"
C_ERR     = "bold red"
C_KEY     = "cyan"
C_VAL     = "white"
C_ENTITY  = "bold magenta"
C_RELATION = "italic bright_blue"

SLASH_COMMANDS = [
    "/search", "/entity", "/path", "/docs", "/stats", "/audit",
    "/concepts", "/experts", "/model", "/clear", "/help", "/?",
    "/exit", "/quit",
]

HISTORY_PATH = Path.home() / ".omnigraph_history"


def _print_header() -> None:
    title = Text.assemble(
        ("◆ ", "bold bright_cyan"),
        ("omni", "bold cyan"),
        ("graph", "bold bright_white"),
    )
    subtitle = Text("enterprise knowledge graph console", style="dim cyan")

    grid = Table.grid(padding=(0, 0))
    grid.add_column(justify="center")
    grid.add_row(title)
    grid.add_row(Text(""))
    grid.add_row(subtitle)

    console.print(
        Panel(
            Align.center(grid),
            box=box.DOUBLE,
            border_style="cyan",
            padding=(1, 10),
        )
    )
    console.print()

    kb = Text()
    kb.append("  /help", style="bold cyan")
    kb.append("  commands    ", style=C_DIM)
    kb.append("tab", style="bold cyan")
    kb.append("  autocomplete    ", style=C_DIM)
    kb.append("^D", style="bold cyan")
    kb.append("  exit", style=C_DIM)
    console.print(kb)
    console.print()


def _help_panel() -> Panel:
    categories = [
        ("search & discovery", [
            ("/search <query>",    "[--strategy hybrid|semantic|fulltext|graph] [--limit N]"),
            ("/concepts <topic>",  "related concepts in the graph"),
            ("/experts <topic>",   "[--limit N]   domain expert lookup"),
        ]),
        ("graph exploration", [
            ("/entity <name|id>",  "[--depth N]   neighborhood walk"),
            ("/path <a> <b>",      "[--depth N]   shortest path between entities"),
        ]),
        ("data & admin", [
            ("/docs",              "[--type T] [--limit N]   list documents"),
            ("/stats",             "graph-wide counts and metrics"),
            ("/audit",             "[--days N] [--limit N]   audit trail"),
        ]),
        ("console", [
            ("/model [id]",        "show or switch the active AI model"),
            ("/clear",             "clear screen"),
            ("/help  /?",          "this help"),
            ("/exit  /quit",       "leave the console"),
        ]),
    ]

    renderables: List = []
    for cat, cmds in categories:
        t = Table.grid(padding=(0, 2))
        t.add_column(style=C_KEY, no_wrap=True, min_width=22)
        t.add_column(style=C_DIM)
        for k, v in cmds:
            t.add_row(k, v)
        renderables.append(Text(f"  {cat}", style=f"bold {C_BRAND}"))
        renderables.append(t)
        renderables.append(Text(""))

    renderables.append(
        Text(
            "  Or just type a question — the agent will answer from the knowledge graph.",
            style=f"italic {C_DIM}",
        )
    )

    return Panel(
        Group(*renderables),
        title="[bold cyan] commands [/]",
        title_align="left",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


# ── Console class ─────────────────────────────────────────────────────────────

class OmniGraphConsole:

    _DEFAULT_MODEL = "claude-opus-4-7"

    def __init__(self) -> None:
        self.db: Optional[DatabaseConnection] = None
        self.graph_builder: Optional[KnowledgeGraphBuilder] = None
        self.query_engine: Optional[SemanticQueryEngine] = None
        self.access_manager: Optional[AccessControlManager] = None
        self.agent = None
        self.current_user_id: Optional[int] = None
        self.current_username: Optional[str] = None
        self.current_fullname: Optional[str] = None
        self._agent_model: str = self._DEFAULT_MODEL
        self._session: Optional[PromptSession] = None

    # ── Startup ───────────────────────────────────────────────────────────

    def run(self) -> None:
        console.clear()
        _print_header()
        console.print()
        self._connect()
        if not self._authenticate():
            self.db.disconnect()
            return
        self._print_welcome()
        self._init_prompt_session()
        self._repl()
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="logout",
            resource_type="system",
            details="Console logout",
        )
        self.db.disconnect()
        console.print()
        console.print(Text("  goodbye.", style=C_DIM))
        console.print()

    def _connect(self) -> None:
        host = settings.db_host
        target = f"{host}/{settings.db_name}"
        with console.status(
            f"[{C_DIM}]connecting to[/] [bold]{target}[/]…",
            spinner="dots",
            spinner_style=C_BRAND,
        ):
            try:
                self.db = DatabaseConnection()
                self.db.connect()
                self.graph_builder = KnowledgeGraphBuilder(self.db)
                self.access_manager = AccessControlManager(self.db)
            except Exception as exc:
                console.print(f"  [{C_ERR}]✗ connection failed:[/] {exc}\n")
                sys.exit(1)
        console.print(f"  [{C_OK}]✓[/] connected to [bold]{target}[/]")

    def _authenticate(self) -> bool:
        console.print()
        try:
            username = console.input(f"  [{C_KEY}]username[/] [dim]›[/] ").strip()
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
            console.print(f"  [{C_ERR}]auth query failed:[/] {exc}")
            return False

        if not row:
            console.print(
                f"  [{C_WARN}]user '{username}' not found or inactive.[/]"
            )
            return False

        self.current_user_id, full_name = row
        self.current_username = username
        self.current_fullname = full_name
        self.query_engine = SemanticQueryEngine(self.db, user_id=self.current_user_id)
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="login",
            resource_type="system",
            details=f"Console login: {username}",
        )
        return True

    def _print_welcome(self) -> None:
        info = Table.grid(padding=(0, 3))
        info.add_column(style=f"bold {C_DIM}", no_wrap=True, justify="right")
        info.add_column(style=C_VAL)
        info.add_row(
            "user",
            Text.assemble(
                (self.current_fullname or "", f"bold {C_OK}"),
                ("  ", ""),
                (f"({self.current_username})", C_DIM),
            ),
        )
        info.add_row(
            "host",
            Text.assemble(
                (settings.db_host, "bold"),
                ("/", C_DIM),
                (settings.db_name, "bold"),
            ),
        )
        info.add_row("model", Text(self._agent_model, style=C_BRAND))
        console.print()
        console.print(
            Panel(
                Align.center(info),
                title=f"[{C_DIM}]● session[/]",
                title_align="left",
                box=box.ROUNDED,
                border_style=C_DIM,
                padding=(0, 4),
            )
        )
        console.print()

    # ── prompt_toolkit setup ──────────────────────────────────────────────

    def _init_prompt_session(self) -> None:
        completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, sentence=False)
        style = PTStyle.from_dict({
            "prompt.brand":   "ansicyan bold",
            "prompt.sep":     "ansibrightblack",
            "prompt.user":    "ansibrightblack",
            "prompt.arrow":   "ansicyan bold",
            "bottom-toolbar": "bg:#1a1a2e #606080",
        })
        self._session = PromptSession(
            history=FileHistory(str(HISTORY_PATH)),
            completer=completer,
            complete_while_typing=True,
            style=style,
            bottom_toolbar=self._bottom_toolbar,
        )

    def _bottom_toolbar(self) -> ANSI:
        return ANSI(
            f"\x1b[1;36m ◆ omni\x1b[0m"
            f"\x1b[90m  ·  \x1b[0m"
            f"\x1b[37m{self.current_username}\x1b[0m"
            f"\x1b[90m  ·  \x1b[0m"
            f"\x1b[37m{self._agent_model}\x1b[0m"
            f"\x1b[90m  ·  \x1b[0m"
            f"\x1b[37m{settings.db_host}/{settings.db_name}\x1b[0m"
            f"\x1b[90m  ·  ^C cancel  ·  ^D exit \x1b[0m"
        )

    def _read_prompt(self) -> Optional[str]:
        # Two-line shell-style prompt — measures width correctly via raw ANSI.
        prompt_ansi = ANSI(
            f"\n \x1b[1;36m╭─◆ omni\x1b[0m"
            f"\x1b[90m ─── {self.current_username} \x1b[0m"
            f"\n \x1b[1;36m╰─›\x1b[0m "
        )
        try:
            return self._session.prompt(prompt_ansi).strip()
        except KeyboardInterrupt:
            return ""
        except EOFError:
            return None

    # ── REPL ─────────────────────────────────────────────────────────────

    def _repl(self) -> None:
        while True:
            line = self._read_prompt()
            if line is None:
                break
            if not line:
                continue
            if line.startswith("/"):
                if self._dispatch_command(line):
                    break
            else:
                self._run_agent(line)

    def _dispatch_command(self, line: str) -> bool:
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
            "clear":    (lambda a: console.clear(),            False),
            "exit":     (lambda a: None,                       True),
            "quit":     (lambda a: None,                       True),
        }

        entry = handlers.get(cmd)
        if entry is None:
            console.print(
                f"  [{C_WARN}]unknown command[/] [b]/{cmd}[/]. "
                f"type [b]/help[/]."
            )
            return False

        fn, should_exit = entry
        if not should_exit:
            try:
                fn(args)
            except Exception as exc:
                logger.exception("Command /%s failed", cmd)
                console.print(f"  [{C_ERR}]command error:[/] {exc}")
        return should_exit

    # ── Agent ─────────────────────────────────────────────────────────────

    def _run_agent(self, question: str) -> None:
        if self.agent is None:
            with console.status(
                f"[{C_DIM}]initializing[/] [bold]{self._agent_model}[/]…",
                spinner="dots",
                spinner_style=C_BRAND,
            ):
                self.agent = get_anthropic_agent(
                    self.db, self.current_user_id, model=self._agent_model
                )
        if self.agent is None:
            console.print(
                f"\n  [{C_WARN}]agent unavailable —[/] set ANTHROPIC_API_KEY, "
                f"or use [b]/search[/] for keyword queries."
            )
            return

        console.print()
        console.print(Text("  thinking…", style=f"italic {C_DIM}"))

        text_started = {"v": False}
        full_text: List[str] = []

        def on_tool_call(name: str, args: Dict) -> None:
            if text_started["v"]:
                console.print()
                text_started["v"] = False
            arg_summary = _format_tool_args(args)
            console.print(
                f"  [{C_DIM}]● {name}([/]"
                f"[italic {C_DIM}]{arg_summary}[/]"
                f"[{C_DIM}])[/]"
            )

        def on_text_chunk(chunk: str) -> None:
            if not text_started["v"]:
                console.print()
                text_started["v"] = True
            full_text.append(chunk)
            # Stream raw — Markdown rendering on partial text is unreliable.
            console.out(chunk, end="", highlight=False)

        try:
            result = self.agent.run(
                question,
                on_tool_call=on_tool_call,
                on_text_chunk=on_text_chunk,
            )
        except KeyboardInterrupt:
            console.print(f"\n  [{C_WARN}]cancelled.[/]")
            return
        except Exception as exc:
            logger.exception("Agent run failed")
            console.print(f"\n  [{C_ERR}]agent error:[/] {exc}")
            return

        if text_started["v"]:
            console.print()
        elif result.get("answer"):
            # No streaming happened — render the full answer as Markdown.
            console.print()
            console.print(
                Panel(
                    Markdown(result["answer"]),
                    title=f"[{C_DIM}]◆ response[/]",
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(1, 2),
                )
            )

        citations = result.get("citations") or []
        if citations:
            parts = [
                f"[{c['document_id']}] {str(c.get('title', ''))[:40]}"
                for c in citations
            ]
            console.print(
                f"\n  [{C_DIM}]sources:[/] "
                f"[italic {C_DIM}]{' · '.join(parts)}[/]"
            )

        self._audit("view", "system", details=f"Agent: {question[:80]}")

    # ── Slash command handlers ────────────────────────────────────────────

    def _cmd_help(self) -> None:
        console.print()
        console.print(_help_panel())

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
        with console.status(
            f"[{C_DIM}]searching[/] [italic]\"{query}\"[/] "
            f"[{C_DIM}]({ns.strategy})…[/]",
            spinner="dots",
            spinner_style=C_BRAND,
        ):
            results = self.query_engine.search(
                query, strategy=ns.strategy, limit=ns.limit
            )
            readable = self._filter_readable(results)

        if not readable:
            console.print(f"  [{C_WARN}]no results.[/]")
            return

        t = _table("results", ["#", "id", "title", "type", "score"])
        for i, r in enumerate(readable):
            t.add_row(
                str(i + 1),
                str(r["document_id"]),
                r["title"][:60],
                r["source_type"],
                f"{r['score']:.3f}",
            )
        console.print()
        console.print(t)
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
            console.print(
                f"  [{C_WARN}]no neighbors found for entity[/] [b]#{entity_id}[/]."
            )
            return

        t = _table(
            f"neighborhood of #{entity_id} (depth {ns.depth})",
            ["id", "name", "type", "relation", "strength", "depth"],
        )
        for n in neighbors:
            t.add_row(
                str(n["entity_id"]),
                Text(n["name"], style=C_ENTITY).plain,
                n["entity_type"],
                Text(n["relation_type"], style=C_RELATION).plain,
                f"{n['strength']:.3f}",
                str(n["depth"]),
            )
        console.print()
        console.print(t)

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
            console.print(f"  [{C_WARN}]path lookup failed:[/] {exc}")
            return

        if not rows:
            console.print(
                f"  [{C_WARN}]no path found between[/] [b]#{source_id}[/] "
                f"[{C_WARN}]and[/] [b]#{target_id}[/]."
            )
            return

        console.print()
        for i, row in enumerate(rows):
            length, entities, relations = row[0], row[1], row[2]
            line = Text()
            for j, ent in enumerate(entities):
                line.append(str(ent), style=C_ENTITY)
                if j < len(relations):
                    line.append("  ─[ ", style=C_DIM)
                    line.append(str(relations[j]), style=C_RELATION)
                    line.append(" ]─▶  ", style=C_DIM)
            console.print(
                Panel(
                    line,
                    title=f"[bold cyan]path {i + 1}[/]  [dim]length={length}[/]",
                    title_align="left",
                    border_style="cyan",
                    box=box.ROUNDED,
                    padding=(0, 2),
                )
            )

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
            console.print(f"  [{C_WARN}]query failed:[/] {exc}")
            return

        t = _table(
            "documents",
            ["id", "title", "type", "sensitivity", "created"],
        )
        for r in rows_raw:
            t.add_row(str(r[0]), r[1][:60], r[2], r[3], r[4])
        console.print()
        console.print(t)

    def _cmd_stats(self) -> None:
        stats = self.graph_builder.get_graph_stats()

        overview = _table("graph", ["metric", "count"], show_header=False)
        for label, key in [
            ("documents",      "total_documents"),
            ("entities",       "total_entities"),
            ("relations",      "total_relations"),
            ("concepts",       "total_concepts"),
            ("taxonomy nodes", "total_taxonomy_nodes"),
        ]:
            overview.add_row(label, f"[bold]{stats.get(key, 0):,}[/]")

        renderables = [overview]
        by_type = stats.get("entities_by_type", {})
        if by_type:
            t = _table("entities by type", ["type", "count"], show_header=False)
            for k, v in sorted(by_type.items(), key=lambda x: -x[1]):
                t.add_row(k, f"[bold]{v:,}[/]")
            renderables.append(t)

        console.print()
        console.print(Columns(renderables, padding=(0, 4), equal=False))
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
            console.print(
                f"\n  [{C_DIM}]no audit entries in the last {ns.days} days.[/]"
            )
            return

        t = _table(
            f"audit trail · last {ns.days}d",
            ["time", "user", "action", "resource", "id", "details"],
        )
        for e in entries:
            t.add_row(
                str(e["timestamp"])[:16],
                str(e.get("user", ""))[:18],
                e.get("action", ""),
                e.get("resource_type", ""),
                str(e.get("resource_id", "") or ""),
                str(e.get("details", "") or "")[:48],
            )
        console.print()
        console.print(t)
        self._audit("view", "system", details=f"Viewed audit trail (last {ns.days}d)")

    def _cmd_concepts(self, args: str) -> None:
        topic = args.strip()
        if not topic:
            console.print(f"  [{C_DIM}]usage: /concepts <topic>[/]")
            return

        related = self.query_engine.find_related_concepts(topic)
        if not related:
            console.print(f"  [{C_WARN}]no related concepts for '{topic}'.[/]")
            return

        t = _table(
            f"related to '{topic}'",
            ["concept", "domain", "relation", "strength"],
        )
        for c in related[:20]:
            t.add_row(
                c["name"],
                c.get("domain", ""),
                c.get("relationship_types", ""),
                f"{c['connection_strength']:.3f}",
            )
        console.print()
        console.print(t)

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
            console.print(f"  [{C_WARN}]no experts found for '{topic}'.[/]")
            return

        t = _table(f"experts · '{topic}'", ["name", "department", "score"])
        for e in experts:
            t.add_row(
                e["full_name"],
                e.get("department", ""),
                f"{e.get('expertise_score', 0):.2f}",
            )
        console.print()
        console.print(t)

    def _cmd_model(self, args: str) -> None:
        model = args.strip()
        if not model:
            current = self.agent.model if self.agent else self._agent_model
            console.print(
                f"  current model: [{C_BRAND}]{current}[/]\n"
                f"  [{C_DIM}]usage: /model <model-id>  "
                f"(e.g. claude-sonnet-4-6, claude-opus-4-7)[/]"
            )
            return
        self._agent_model = model
        self.agent = None
        console.print(f"  [{C_OK}]✓[/] model set to [bold]{model}[/]")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _parse(
        self,
        prog: str,
        args: str,
        spec: list,
        usage: str = "",
    ) -> Optional[argparse.Namespace]:
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
                console.print(f"  [{C_DIM}]usage:[/] {usage}")
            return None

    def _resolve_entity_id(self, value: str) -> Optional[int]:
        value = value.strip()
        if not value:
            console.print(f"  [{C_WARN}]no entity specified.[/]")
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
            console.print(f"  [{C_WARN}]entity lookup error:[/] {exc}")
            return None

        if not matches:
            console.print(f"  [{C_WARN}]no entity found for '{value}'.[/]")
            return None

        exact = [m for m in matches if m["name"].lower() == value.lower()]
        if len(exact) == 1:
            return exact[0]["entity_id"]

        console.print(f"\n  [{C_DIM}]multiple matches for '{value}':[/]")
        t = _table(None, ["id", "name", "type", "conf", "docs"])
        for m in matches:
            t.add_row(
                str(m["entity_id"]),
                m["name"][:40],
                m["entity_type"],
                f"{m['confidence']:.3f}",
                str(m["doc_count"]),
            )
        console.print(t)
        try:
            raw = console.input(f"  [{C_KEY}]entity id ›[/] ").strip()
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


# ── Render helpers ────────────────────────────────────────────────────────────

def _table(title: Optional[str], headers: List[str], show_header: bool = True) -> Table:
    t = Table(
        title=f"[bold cyan]{title}[/]" if title else None,
        title_justify="left",
        box=box.SIMPLE_HEAVY,
        header_style=f"bold {C_KEY}",
        border_style=C_DIM,
        show_header=show_header,
        expand=False,
        padding=(0, 1),
    )
    for h in headers:
        t.add_column(h, overflow="fold")
    return t


def _format_tool_args(args: Dict) -> str:
    parts = []
    for k, v in args.items():
        s = repr(v)
        parts.append(f"{k}={s[:40]}{'…' if len(s) > 40 else ''}")
    return ", ".join(parts)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = OmniGraphConsole()
    try:
        app.run()
    except KeyboardInterrupt:
        console.print(f"\n\n  [{C_DIM}]interrupted. goodbye.[/]\n")
    except Exception as exc:
        console.print(f"\n  [{C_ERR}]fatal error:[/] {exc}")
        logger.exception("Fatal error in console application")
        sys.exit(1)
