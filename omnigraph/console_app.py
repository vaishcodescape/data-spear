import logging
import os
import re
import sys
from getpass import getpass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import find_dotenv, load_dotenv  # type: ignore[import-untyped]

import psycopg2  # type: ignore[import-untyped]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from omnigraph.access_control_audit import AccessControlManager
from omnigraph.agentic_rag import get_anthropic_agent
from omnigraph.graph_builder import KnowledgeGraphBuilder
from omnigraph.ingestion_pipeline import DatabaseConnection
from omnigraph.semantic_query_engine import SemanticQueryEngine

_PROJECT_ENV = _PROJECT_ROOT / ".env"
load_dotenv(_PROJECT_ENV)
load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("omnigraph.console")

# Visual constants

BOX_W = 64
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

LOGO = f"""{CYAN}
    ___                  _  ____                 _
   / _ \\ _ __ ___  _ __ (_)/ ___|_ __ __ _ _ __ | |__
  | | | | '_ ` _ \\| '_ \\| | |  _| '__/ _` | '_ \\| '_ \\
  | |_| | | | | | | | | | | |_| | | | (_| | |_) | | | |
   \\___/|_| |_| |_|_| |_|_|\\____|_|  \\__,_| .__/|_| |_|
                                            |_|
{RESET}"""


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _box_top() -> str:
    return f"  {DIM}+{'=' * BOX_W}+{RESET}"


def _box_mid() -> str:
    return f"  {DIM}+{'-' * BOX_W}+{RESET}"


def _box_bot() -> str:
    return f"  {DIM}+{'=' * BOX_W}+{RESET}"


def _box_row(text: str, align: str = "left") -> str:
    stripped = _strip_ansi(text)
    pad = BOX_W - 2 - len(stripped)
    if pad < 0:
        text = text[: BOX_W - 2]
        pad = 0
    if align == "center":
        left_pad = pad // 2
        right_pad = pad - left_pad
        inner = " " * left_pad + text + " " * right_pad
    else:
        inner = " " + text + " " * (pad - 1) if pad > 0 else " " + text
    return f"  {DIM}|{RESET}{inner}{DIM}|{RESET}"


def print_header(title: str) -> None:
    print()
    print(_box_top())
    print(_box_row(f"{BOLD}{CYAN}{title}{RESET}", align="center"))
    print(_box_bot())


def print_section(title: str) -> None:
    print(f"\n  {BOLD}{title}{RESET}")
    print(f"  {DIM}{'.' * (BOX_W - 4)}{RESET}")


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
    header_line = "".join(f"{BOLD}{str(h).ljust(w)}{RESET}" for h, w in zip(headers, widths))
    print(f"  {header_line}")
    print(f"  {DIM}{''.join('-' * w for w in widths)}{RESET}")
    for row in rows:
        cells = []
        for i, w in enumerate(widths):
            val = str(row[i] if i < len(row) else "")
            cells.append(val.ljust(w)[:w])
        print(f"  {''.join(cells)}")


def prompt_int(message: str, default: Optional[int] = None) -> Optional[int]:
    suffix = f" {DIM}[{default}]{RESET}" if default is not None else ""
    try:
        value = input(f"  {message}{suffix}: ").strip()
        return default if not value and default is not None else int(value)
    except (EOFError, ValueError):
        return default


def prompt_str(message: str, default: str = "") -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    try:
        value = input(f"  {message}{suffix}: ").strip()
        return value or default
    except EOFError:
        return default


class OmniGraphConsole:
    """Focused console for OmniGraph: Graph Search, Agent, and Relations."""

    def __init__(self):
        self.db = None
        self.graph_builder = None
        self.query_engine = None
        self.access_manager = None
        self.agent = None
        self.current_user_id = None
        self.current_username = None

    # Connection & Auth

    def connect(
        self,
        host: str = "localhost",
        port: int = 5432,
        dbname: str = "omnigraph",
        user: str = "postgres",
        password: Optional[str] = None,
    ) -> None:
        self.db = DatabaseConnection(host, port, dbname, user, password)
        self.db.connect()
        self.graph_builder = KnowledgeGraphBuilder(self.db)
        self.access_manager = AccessControlManager(self.db)

    def authenticate(self) -> bool:
        print_header("Login")
        username = prompt_str("Username")
        if not username:
            return False

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

        if not row:
            print(f"\n  {YELLOW}User not found or inactive.{RESET}\n")
            return False

        self.current_user_id, self.current_username = row
        self.query_engine = SemanticQueryEngine(self.db, user_id=self.current_user_id)
        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="login",
            resource_type="system",
            details=f"Console login: {username}",
        )
        print(f"\n  {GREEN}Welcome, {self.current_username}.{RESET}\n")
        return True

    #  Main loop 

    def run(self) -> None:
        print(LOGO)
        print_header("Connect to Database")

        host = prompt_str("Database host", "localhost")
        port = prompt_int("Database port", 5432)
        dbname = prompt_str("Database name", "omnigraph")
        db_user = prompt_str("Database user", os.getenv("OMNIGRAPH_DB_USER", "postgres"))
        try:
            db_pass = getpass("  Database password (leave blank for env): ") or None
        except (EOFError, KeyboardInterrupt):
            db_pass = None

        try:
            self.connect(host, port, dbname, db_user, db_pass)
        except Exception as exc:
            print(f"\n  {YELLOW}Connection failed: {exc}{RESET}")
            return

        if not self.authenticate():
            print(f"  {DIM}Exiting.{RESET}\n")
            return

        self._main_menu()

        self.access_manager.log_audit(
            user_id=self.current_user_id,
            action="logout",
            resource_type="system",
            details="Console logout",
        )
        self.db.disconnect()
        print(f"\n  {DIM}Goodbye.{RESET}\n")

    def _main_menu(self) -> None:
        while True:
            print()
            print(_box_top())
            print(_box_row(f"{BOLD}{CYAN}OmniGraph Console{RESET}", align="center"))
            print(_box_mid())
            print(_box_row(f"{GREEN}[1]{RESET} Graph Search    {DIM}Search the knowledge graph{RESET}"))
            print(_box_row(f"{GREEN}[2]{RESET} Agent Prompt    {DIM}Ask the AI agent a question{RESET}"))
            print(_box_row(f"{GREEN}[3]{RESET} Relations       {DIM}Explore entity relationships{RESET}"))
            print(_box_row(f"{GREEN}[4]{RESET} Administration  {DIM}Stats, audit trail, and roles{RESET}"))
            print(_box_mid())
            print(_box_row(f"{DIM}[q] Quit{RESET}"))
            print(_box_bot())

            choice = prompt_str("Choose").strip().lower()

            if choice in {"q", "quit", "exit"}:
                break
            elif choice == "1":
                self._graph_search_menu()
            elif choice == "2":
                self._agent_prompt()
            elif choice == "3":
                self._relations_menu()
            elif choice == "4":
                self._admin_menu()
            else:
                print(f"  {YELLOW}Invalid choice. Enter 1-4 or q.{RESET}")

    # Graph Search 

    def _graph_search_menu(self) -> None:
        print_header("Graph Search")
        query = prompt_str("Search query")
        if not query:
            return

        print()
        print(_box_top())
        print(_box_row(f"{BOLD}Search Strategy{RESET}", align="center"))
        print(_box_mid())
        print(_box_row(f"{GREEN}[1]{RESET} Hybrid     {DIM}Full-text + Semantic + Graph (recommended){RESET}"))
        print(_box_row(f"{GREEN}[2]{RESET} Semantic   {DIM}Vector similarity search{RESET}"))
        print(_box_row(f"{GREEN}[3]{RESET} Full-text  {DIM}Keyword matching{RESET}"))
        print(_box_row(f"{GREEN}[4]{RESET} Graph      {DIM}Entity-based graph traversal{RESET}"))
        print(_box_bot())

        strat_choice = prompt_str("Strategy", "1").strip()
        strategy_map = {"1": "hybrid", "2": "semantic", "3": "fulltext", "4": "graph"}
        strategy = strategy_map.get(strat_choice, "hybrid")
        limit = prompt_int("Max results", 10)

        print_section(f"Results for \"{query}\" ({strategy})")

        results = self.query_engine.search(query, strategy=strategy, limit=limit)
        results = self._filter_readable(results)

        rows = [
            [
                r["document_id"],
                r["title"][:38],
                r["source_type"],
                f"{r['score']:.3f}",
                ", ".join(r.get("sources", [])),
            ]
            for r in results
        ]
        print_table(
            ["ID", "Title", "Type", "Score", "Sources"],
            rows,
            [6, 40, 16, 8, 24],
        )

        self._audit("search", "document", details=f"Graph search: {query[:80]}")

    # Agent Prompt

    def _agent_prompt(self) -> None:
        print_header("Agent Prompt")
        print(f"  {DIM}Ask the AI agent anything about your knowledge graph.{RESET}")
        print(f"  {DIM}Type 'back' to return to the main menu.{RESET}\n")

        if self.agent is None:
            self.agent = get_anthropic_agent(self.db, self.current_user_id)
        if self.agent is None:
            print(f"  {YELLOW}Agent unavailable. Set ANTHROPIC_API_KEY to enable.{RESET}")
            return

        while True:
            try:
                question = input(f"\n  {CYAN}You:{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            if question.lower() in {"back", "exit", "quit", "q"}:
                break

            print(f"\n  {DIM}Thinking...{RESET}")
            try:
                result = self.agent.run(question)
                self._render_agent_result(result)
                self._audit("view", "system", details=f"Agent question: {question[:80]}")
            except Exception as exc:
                logger.exception("Agent failed")
                print(f"  {YELLOW}Agent error: {exc}{RESET}")

    def _render_agent_result(self, result: dict) -> None:
        answer = (result.get("answer") or "").strip()
        tools_used = result.get("tools_used") or []
        citations = result.get("citations") or []

        if not answer:
            print(f"  {YELLOW}No answer returned.{RESET}")
            return

        print_section("Answer")
        for line in answer.split("\n"):
            print(f"  {line}")

        if tools_used:
            print_section("Tools Used")
            rows = [
                [i + 1, t.get("name", ""), ", ".join(f"{k}={v}" for k, v in (t.get("input") or {}).items())[:60]]
                for i, t in enumerate(tools_used)
            ]
            print_table(["#", "Tool", "Input"], rows, [4, 24, 62])

        if citations:
            print_section("Citations")
            rows = [[c["document_id"], str(c.get("title", ""))[:50], c.get("source_type", "")]
                    for c in citations]
            print_table(["Doc ID", "Title", "Type"], rows, [8, 52, 18])

    # Relations

    def _relations_menu(self) -> None:
        while True:
            print()
            print(_box_top())
            print(_box_row(f"{BOLD}{CYAN}Entity Relations{RESET}", align="center"))
            print(_box_mid())
            print(_box_row(f"{GREEN}[1]{RESET} Path Between      {DIM}Shortest path between two entities{RESET}"))
            print(_box_row(f"{GREEN}[2]{RESET} Neighborhood      {DIM}Explore an entity's neighbors{RESET}"))
            print(_box_row(f"{GREEN}[3]{RESET} Related Concepts  {DIM}Find concepts related to a topic{RESET}"))
            print(_box_row(f"{GREEN}[4]{RESET} Entity Documents  {DIM}Documents linked to an entity{RESET}"))
            print(_box_mid())
            print(_box_row(f"{DIM}[b] Back{RESET}"))
            print(_box_bot())

            choice = prompt_str("Choose").strip().lower()

            if choice in {"b", "back", "q"}:
                break
            elif choice == "1":
                self._entity_path()
            elif choice == "2":
                self._entity_neighborhood()
            elif choice == "3":
                self._related_concepts()
            elif choice == "4":
                self._entity_documents()
            else:
                print(f"  {YELLOW}Invalid choice.{RESET}")

    def _entity_path(self) -> None:
        print_section("Shortest Path")
        source = prompt_str("Source entity (name or ID)")
        target = prompt_str("Target entity (name or ID)")
        source_id = self._resolve_entity_id(source)
        target_id = self._resolve_entity_id(target)
        if source_id is None or target_id is None:
            return
        max_depth = prompt_int("Max depth", 6)

        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM omnigraph.sp_shortest_path(%s, %s, %s)",
                    (source_id, target_id, max_depth),
                )
                rows = cur.fetchall()
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            print(f"\n  {YELLOW}Path lookup failed: {exc}{RESET}")
            return

        if not rows:
            print(f"\n  {YELLOW}No path found between entity #{source_id} and #{target_id}.{RESET}")
            return

        for i, row in enumerate(rows):
            print(f"\n  {GREEN}Path {i + 1}{RESET} {DIM}(length={row[0]}){RESET}")
            entities = row[1]
            relations = row[2]
            parts = []
            
            for j, ent in enumerate(entities):
                parts.append(f"{BOLD}{ent}{RESET}")
                if j < len(relations):
                    parts.append(f" {DIM}--[{relations[j]}]-->{RESET} ")
            print(f"    {''.join(parts)}")

    def _entity_neighborhood(self) -> None:
        print_section("Entity Neighborhood")
        entity = prompt_str("Entity name or ID")
        entity_id = self._resolve_entity_id(entity)
        if entity_id is None:
            return
        depth = prompt_int("Max depth", 2)

        neighbors = self.graph_builder.get_entity_neighborhood(entity_id, depth)
        rows = [
            [
                n["entity_id"],
                n["name"],
                n["entity_type"],
                n["relation_type"],
                f"{n['strength']:.3f}",
                n["depth"],
            ]
            for n in neighbors
        ]
        print_table(
            ["ID", "Name", "Type", "Relation", "Strength", "Depth"],
            rows,
            [6, 22, 14, 18, 10, 6],
        )

    def _related_concepts(self) -> None:
        print_section("Related Concepts")
        concept = prompt_str("Concept name")
        if not concept:
            return

        related = self.query_engine.find_related_concepts(concept)
        rows = [
            [c["name"], c["domain"], c["relationship_types"], c["connection_strength"]]
            for c in related
        ]
        print_table(
            ["Concept", "Domain", "Relation", "Strength"],
            rows,
            [28, 16, 25, 10],
        )

    def _entity_documents(self) -> None:
        print_section("Entity Documents")
        entity = prompt_str("Entity name")
        if not entity:
            return

        docs = self._filter_readable(self.query_engine.get_entity_documents(entity))
        rows = [
            [
                d["document_id"],
                d["title"][:40],
                d["source_type"],
                f"{d['relevance']:.3f}",
                d["mention_count"],
            ]
            for d in docs
        ]
        print_table(
            ["ID", "Title", "Type", "Relevance", "Mentions"],
            rows,
            [6, 42, 16, 10, 10],
        )

    # Administration

    def _admin_menu(self) -> None:
        while True:
            print()
            print(_box_top())
            print(_box_row(f"{BOLD}{CYAN}Administration{RESET}", align="center"))
            print(_box_mid())
            print(_box_row(f"{GREEN}[1]{RESET} Graph Statistics      {DIM}Entity, relation, and concept counts{RESET}"))
            print(_box_row(f"{GREEN}[2]{RESET} Audit Trail           {DIM}Recent user activity log{RESET}"))
            print(_box_row(f"{GREEN}[3]{RESET} Query Analytics       {DIM}Search usage statistics{RESET}"))
            print(_box_row(f"{GREEN}[4]{RESET} My Roles & Access     {DIM}Your permissions and role assignments{RESET}"))
            print(_box_row(f"{GREEN}[5]{RESET} Sensitive Access Log  {DIM}Confidential document access history{RESET}"))
            print(_box_mid())
            print(_box_row(f"{DIM}[b] Back{RESET}"))
            print(_box_bot())

            choice = prompt_str("Choose").strip().lower()

            if choice in {"b", "back", "q"}:
                break
            elif choice == "1":
                self._graph_stats()
            elif choice == "2":
                self._audit_trail()
            elif choice == "3":
                self._query_analytics()
            elif choice == "4":
                self._my_roles()
            elif choice == "5":
                self._sensitive_access_report()
            else:
                print(f"  {YELLOW}Invalid choice.{RESET}")

    def _graph_stats(self) -> None:
        print_header("Graph Statistics")
        stats = self.graph_builder.get_graph_stats()

        print_section("Overview")
        overview = [
            ["Entities", stats.get("total_entities", 0)],
            ["Relations", stats.get("total_relations", 0)],
            ["Concepts", stats.get("total_concepts", 0)],
            ["Documents", stats.get("total_documents", 0)],
            ["Taxonomy Nodes", stats.get("total_taxonomy_nodes", 0)],
        ]
        print_table(["Metric", "Count"], overview, [24, 10])

        entities_by_type = stats.get("entities_by_type", {})
        if entities_by_type:
            print_section("Entities by Type")
            rows = [[k, v] for k, v in sorted(entities_by_type.items(), key=lambda x: -x[1])]
            print_table(["Entity Type", "Count"], rows, [24, 10])

        relations_by_type = stats.get("relations_by_type", {})
        if relations_by_type:
            print_section("Relations by Type")
            rows = [[k, v] for k, v in sorted(relations_by_type.items(), key=lambda x: -x[1])]
            print_table(["Relation Type", "Count"], rows, [28, 10])

        self._audit("view", "system", details="Viewed graph statistics")

    def _audit_trail(self) -> None:
        print_header("Audit Trail")
        days = prompt_int("Show last N days", 7)
        limit = prompt_int("Max entries", 25)

        entries = self.access_manager.get_audit_trail(days=days, limit=limit)
        if not entries:
            print(f"\n  {DIM}No audit entries in the last {days} days.{RESET}")
            return

        rows = [
            [
                str(e["timestamp"])[:16],
                str(e.get("user", ""))[:18],
                e.get("action", ""),
                e.get("resource_type", ""),
                str(e.get("resource_id", "") or ""),
                str(e.get("details", "") or "")[:30],
            ]
            for e in entries
        ]
        print_table(
            ["Time", "User", "Action", "Resource", "ID", "Details"],
            rows,
            [17, 20, 14, 12, 5, 32],
        )
        self._audit("view", "system", details=f"Viewed audit trail (last {days}d)")

    def _query_analytics(self) -> None:
        print_header("Query Analytics")
        days = prompt_int("Show last N days", 30)

        analytics = self.access_manager.get_query_analytics(days=days)
        if not analytics:
            print(f"\n  {DIM}No query data available.{RESET}")
            return

        by_type = analytics.get("by_type", [])
        if by_type:
            print_section("Queries by Type")
            rows = [
                [
                    q["query_type"],
                    q["count"],
                    f"{q['avg_execution_ms']:.0f} ms",
                    f"{q['avg_results']:.1f}",
                ]
                for q in by_type
            ]
            print_table(["Type", "Count", "Avg Time", "Avg Results"], rows, [20, 8, 12, 14])

        top_users = analytics.get("top_users", [])
        if top_users:
            print_section("Top Users")
            rows = [[u["user"], u["query_count"]] for u in top_users]
            print_table(["User", "Queries"], rows, [34, 10])

        self._audit("view", "system", details=f"Viewed query analytics (last {days}d)")

    def _my_roles(self) -> None:
        print_header("My Roles & Permissions")

        roles = self.access_manager.get_user_roles(self.current_user_id)
        if not roles:
            print(f"\n  {DIM}No roles assigned to your account.{RESET}")
        else:
            print_section("Assigned Roles")
            rows = [
                [
                    r["role_name"],
                    str(r.get("description", "") or "")[:38],
                    str(r.get("assigned_at", ""))[:16],
                ]
                for r in roles
            ]
            print_table(["Role", "Description", "Assigned At"], rows, [20, 40, 18])

        matrix = self.access_manager.get_user_access_matrix(self.current_user_id)
        if matrix:
            print_section("Access Matrix")
            rows = [
                [
                    m["resource_type"],
                    m["sensitivity_level"],
                    f"{GREEN}Y{RESET}" if m["can_read"] else f"{DIM}N{RESET}",
                    f"{GREEN}Y{RESET}" if m["can_write"] else f"{DIM}N{RESET}",
                    f"{YELLOW}Y{RESET}" if m["can_delete"] else f"{DIM}N{RESET}",
                ]
                for m in matrix
            ]
            print_table(
                ["Resource", "Sensitivity", "Read", "Write", "Delete"],
                rows,
                [16, 16, 6, 7, 8],
            )

    def _sensitive_access_report(self) -> None:
        print_header("Sensitive Access Report")
        days = prompt_int("Show last N days", 30)

        report = self.access_manager.get_sensitive_access_report(days=days)
        if not report:
            print(f"\n  {DIM}No sensitive document access in the last {days} days.{RESET}")
            return

        rows = [
            [
                str(r["timestamp"])[:16],
                str(r.get("user", ""))[:16],
                r.get("action", ""),
                str(r.get("document", "") or "")[:28],
                r.get("sensitivity", ""),
            ]
            for r in report
        ]
        print_table(
            ["Time", "User", "Action", "Document", "Sensitivity"],
            rows,
            [17, 18, 10, 30, 14],
        )
        self._audit("view", "system", details=f"Viewed sensitive access report (last {days}d)")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _resolve_entity_id(self, value: str) -> Optional[int]:
        value = value.strip()
        if not value:
            print(f"  {YELLOW}No entity specified.{RESET}")
            return None
        if value.isdigit():
            return int(value)

        matches = self._find_entity_candidates(value)
        if not matches:
            print(f"  {YELLOW}No entity found for '{value}'.{RESET}")
            return None
        exact = [m for m in matches if m["name"].lower() == value.lower()]
        if len(exact) == 1:
            return exact[0]["entity_id"]

        print(f"\n  {DIM}Multiple matches for '{value}':{RESET}")
        print_table(
            ["ID", "Name", "Type", "Confidence", "Docs"],
            [
                [m["entity_id"], m["name"][:32], m["entity_type"], f"{m['confidence']:.3f}", m["doc_count"]]
                for m in matches
            ],
            [6, 34, 16, 12, 6],
        )
        return prompt_int("Use entity ID")

    def _find_entity_candidates(self, term: str, limit: int = 10) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.entity_id, e.name, e.entity_type, e.confidence,
                           (SELECT COUNT(*) FROM omnigraph.document_entities de
                            WHERE de.entity_id = e.entity_id) AS doc_count
                    FROM omnigraph.entities e
                    WHERE LOWER(e.name) = LOWER(%s)
                       OR e.name ILIKE %s
                       OR e.description ILIKE %s
                    ORDER BY CASE WHEN LOWER(e.name) = LOWER(%s) THEN 0 ELSE 1 END,
                             doc_count DESC, e.name
                    LIMIT %s
                    """,
                    (term, f"%{term}%", f"%{term}%", term, limit),
                )
                columns = ["entity_id", "name", "entity_type", "confidence", "doc_count"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            print(f"  {YELLOW}Entity lookup error: {exc}{RESET}")
            return []

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


if __name__ == "__main__":
    console = OmniGraphConsole()
    try:
        console.run()
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Interrupted. Goodbye.{RESET}\n")
    except Exception as exc:
        print(f"\n  Fatal error: {exc}")
        logger.exception("Fatal error in console application")
