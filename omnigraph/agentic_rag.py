# RAG Pipeline
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, NamedTuple, Optional

import anthropic

from .access_control_audit import AccessControlManager
from .config import settings
from .ingestion_pipeline import DatabaseConnection
from .semantic_query_engine import SemanticQueryEngine


def _format_docs(docs: List[Dict[str, Any]], max_chars: int = 4000) -> str:
    out: List[str] = []
    total = 0
    for d in docs:
        title = d.get("title", "Untitled")
        summary = (d.get("summary") or "")[:600]
        doc_id = d.get("document_id", "")
        hint = f"  (call get_document_content({doc_id}) for full text)" if doc_id else ""
        line = f"[doc_id={doc_id}] {title}\n  {summary}{hint}"
        if total + len(line) > max_chars:
            break
        out.append(line)
        total += len(line)
    return "\n\n".join(out) if out else "No documents found."


class _OmniTool(NamedTuple):
    schema: Dict[str, Any]
    fn: Callable


def _create_tools(
    query_engine: SemanticQueryEngine,
    access_manager: AccessControlManager,
    user_id: int,
    db: DatabaseConnection,
) -> List[_OmniTool]:

    def hybrid_search(query: str, limit: int = 10) -> str:
        results = query_engine.search(query, strategy="hybrid", limit=limit)
        filtered = [
            r for r in results
            if r.get("document_id") is not None
            and access_manager.check_access(user_id, "document", r["document_id"], "read")
        ]
        return _format_docs(filtered)

    def find_experts(concept: str, limit: int = 5) -> str:
        experts = query_engine.find_experts(concept, limit=limit)
        if not experts:
            return "No experts found for that concept."
        lines = [
            f"- {e['full_name']} ({e.get('department', '')}): {e.get('expertise_score', 0):.1f}"
            for e in experts
        ]
        return "\n".join(lines)

    def get_entity_documents(entity_name: str, limit: int = 10) -> str:
        docs = query_engine.get_entity_documents(entity_name, limit=limit)
        filtered = [
            d for d in docs
            if d.get("document_id") is not None
            and access_manager.check_access(user_id, "document", d["document_id"], "read")
        ]
        return _format_docs(filtered)

    def find_related_concepts(concept: str) -> str:
        related = query_engine.find_related_concepts(concept)
        if not related:
            return "No related concepts found."
        lines = [
            f"- {c['name']} [{c.get('domain', '')}] ({c.get('relationship_types', '')})"
            for c in related[:15]
        ]
        return "\n".join(lines)

    def get_document_content(document_id: int, max_chars: int = 4000) -> str:
        if not access_manager.check_access(user_id, "document", document_id, "read"):
            return "Access denied to this document."
        try:
            with db.conn.cursor() as cur:
                cur.execute(
                    "SELECT title, content FROM omnigraph.documents WHERE document_id = %s",
                    (document_id,),
                )
                row = cur.fetchone()
            if not row:
                return "Document not found."
            title, content = row[0], (row[1] or "")[:max_chars]
            return f"Title: {title}\n\nContent:\n{content}"
        except Exception as e:
            return f"Error fetching document: {e}"

    return [
        _OmniTool(
            schema={
                "name": "hybrid_search",
                "description": "Search the knowledge graph using full-text, semantic, and graph traversal. Use for finding documents relevant to a topic or question.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Maximum number of results (default 10)"},
                    },
                    "required": ["query"],
                },
            },
            fn=hybrid_search,
        ),
        _OmniTool(
            schema={
                "name": "find_experts",
                "description": "Find users who are domain experts on a concept, ranked by document contributions and relevance.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string", "description": "Concept or topic name"},
                        "limit": {"type": "integer", "description": "Maximum number of experts to return (default 5)"},
                    },
                    "required": ["concept"],
                },
            },
            fn=find_experts,
        ),
        _OmniTool(
            schema={
                "name": "get_entity_documents",
                "description": "List documents linked to a specific entity (person, org, technology).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "Entity name to look up"},
                        "limit": {"type": "integer", "description": "Maximum results (default 10)"},
                    },
                    "required": ["entity_name"],
                },
            },
            fn=get_entity_documents,
        ),
        _OmniTool(
            schema={
                "name": "find_related_concepts",
                "description": "Get concepts related to a given concept via hierarchy and co-occurrence in documents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string", "description": "Concept name"},
                    },
                    "required": ["concept"],
                },
            },
            fn=find_related_concepts,
        ),
        _OmniTool(
            schema={
                "name": "get_document_content",
                "description": "Fetch the full text content of a document by ID. Use after search when you need to read the actual content. Requires read access.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "integer", "description": "Document ID"},
                        "max_chars": {"type": "integer", "description": "Maximum characters to return (default 4000)"},
                    },
                    "required": ["document_id"],
                },
            },
            fn=get_document_content,
        ),
    ]


class AnthropicOmniGraphAgent:

    _SYSTEM = """\
You are OmniGraph Assistant, an AI that answers questions from an enterprise knowledge graph.

## RAG Workflow — follow this order for every factual question:
1. **Search first**: call `hybrid_search` with the user's topic/question to find candidate documents.
2. **Read before answering**: for each promising result, call `get_document_content(doc_id)` to fetch the full text. Do not answer from titles or summaries alone.
3. **Cite sources**: every factual claim in your answer must include a `[doc_id=X]` citation referencing the document you read.
4. **Explore the graph**: use `find_related_concepts`, `get_entity_documents`, or `find_experts` when the user's question involves entities, relationships, or expertise.

## Output format:
- Lead with a direct answer to the question.
- Follow with supporting details and `[doc_id=X]` citations.
- If no relevant documents were found after searching, say so clearly rather than guessing.
- Keep responses concise unless the user asks for depth.
"""

    def __init__(
        self,
        db: DatabaseConnection,
        user_id: int,
        model: str = "claude-opus-4-6",
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.model = model
        self.client = anthropic.Anthropic()
        self.access_manager = AccessControlManager(db)
        self.query_engine = SemanticQueryEngine(db, user_id=user_id)
        tools = _create_tools(self.query_engine, self.access_manager, user_id, db)
        self._tool_map: Dict[str, Callable] = {t.schema["name"]: t.fn for t in tools}
        self._anthropic_tools: List[Dict[str, Any]] = [t.schema for t in tools]

    def run(
        self,
        question: str,
        *,
        on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Run the agent loop.

        on_tool_call(name, input) -- called just before each tool executes.
        on_text_chunk(chunk)      -- called for each streamed text token.
        Both callbacks are optional; omitting them gives the original batch behaviour.
        """
        messages: List[Dict[str, Any]] = [{"role": "user", "content": question}]
        tools_used: List[Dict[str, Any]] = []

        while True:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=self._SYSTEM,
                tools=self._anthropic_tools,
                thinking={"type": "adaptive"},
                messages=messages,
            ) as stream:
                if on_text_chunk is not None:
                    for chunk in stream.text_stream:
                        on_text_chunk(chunk)
                response = stream.get_final_message()

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                break

            tool_results: List[Dict[str, Any]] = []
            for block in response.content:
                if block.type == "tool_use":
                    if on_tool_call is not None:
                        on_tool_call(block.name, dict(block.input))
                    fn = self._tool_map.get(block.name)
                    if fn is not None:
                        try:
                            result = fn(**block.input)
                        except Exception as exc:
                            result = f"Tool error: {exc}"
                    else:
                        result = f"Unknown tool: {block.name}"
                    tools_used.append({"name": block.name, "input": dict(block.input)})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            messages.append({"role": "user", "content": tool_results})

        answer = next((b.text for b in response.content if b.type == "text"), "")
        citations = self._extract_citations(answer)
        return {
            "answer": answer,
            "citations": citations,
            "tools_used": tools_used,
            "stop_reason": response.stop_reason,
            "messages": messages,
        }

    def _extract_citations(self, answer: str) -> List[Dict[str, Any]]:
        ids = []
        seen = set()
        for m in re.finditer(r"\[doc_id=(\d+)\]", answer):
            doc_id = int(m.group(1))
            if doc_id not in seen:
                seen.add(doc_id)
                ids.append(doc_id)
        if not ids:
            return []
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id, title, source_type FROM omnigraph.documents "
                    "WHERE document_id = ANY(%s)",
                    (ids,),
                )
                rows = {r[0]: {"document_id": r[0], "title": r[1], "source_type": r[2]}
                        for r in cur.fetchall()}
        except Exception:
            try:
                self.db.conn.rollback()
            except Exception:
                pass
            rows = {}
        return [rows.get(i, {"document_id": i, "title": "(unknown)", "source_type": ""})
                for i in ids]


 
def get_anthropic_agent(
    db: DatabaseConnection,
    user_id: int,
    model: str = "claude-opus-4-6",
) -> Optional[AnthropicOmniGraphAgent]:
    if not settings.anthropic_api_key:
        return None
    return AnthropicOmniGraphAgent(db, user_id, model=model)


__all__ = ["AnthropicOmniGraphAgent", "get_anthropic_agent", "_create_tools", "_format_docs"]
