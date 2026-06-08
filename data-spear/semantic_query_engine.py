# Semantic Query Engine for Omnigraph
import logging
import re
import time
from typing import Dict, List, Optional

import psycopg2

from .embedder import generate_embedding, is_available as _embedder_available

logger = logging.getLogger("omnigraph.query_engine")

_STOP_WORDS = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "with", "by", "from", "that", "this", "these", "those",
    "it", "its", "my", "your", "our", "find", "search", "show", "get", "list",
    "what", "how", "who", "where", "when", "which",
})

_RANK_WEIGHTS = {"fulltext": 1.0, "semantic": 1.2, "graph": 0.8}
_QUERY_TYPE_MAP = {"fulltext": "keyword_search", "semantic": "semantic_search",
                   "graph": "graph_traversal", "hybrid": "semantic_search"}

_semantic_warned = False


# Full-text, vector, graph, and hybrid document search.
class SemanticQueryEngine:

    def __init__(self, db_connection, user_id: Optional[int] = None):
        self.db = db_connection
        self.user_id = user_id

    def search(
        self,
        query: str,
        strategy: str = "hybrid",
        limit: int = 10,
        sensitivity_filter: Optional[List[str]] = None,
    ) -> List[Dict]:
        start_time = time.time()
        parsed = self.parse_query(query)

        if strategy == "fulltext":
            results = self.fulltext_search(query, limit, sensitivity_filter)
        elif strategy == "semantic":
            results = self.vector_similarity_search(query, limit)
        elif strategy == "graph":
            results = self.graph_traverse(parsed, limit)
        else:
            if strategy != "hybrid":
                logger.warning("Unknown strategy '%s', defaulting to hybrid.", strategy)
            results = self._hybrid_search(query, parsed, limit, sensitivity_filter)

        results = self.rank_results(results)
        elapsed_ms = int((time.time() - start_time) * 1000)
        self._log_query(query, strategy, len(results), elapsed_ms)
        logger.info("Search '%s' (%s): %d results in %dms.", query, strategy, len(results), elapsed_ms)
        return results[:limit]

    def fulltext_search(
        self,
        query: str,
        limit: int = 10,
        sensitivity_filter: Optional[List[str]] = None,
    ) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                params: list = [query, query, limit]
                sensitivity_clause = ""
                if sensitivity_filter:
                    sensitivity_clause = "AND d.sensitivity_level = ANY(%s)"
                    params = [query, query, sensitivity_filter, limit]

                cur.execute(
                    f"""
                    SELECT
                        d.document_id, d.title, d.source_type, d.sensitivity_level,
                        ts_rank(to_tsvector('english', d.title || ' ' || d.content),
                                plainto_tsquery('english', %s)) AS search_rank,
                        LEFT(d.summary, 200) AS summary,
                        u.full_name AS author, d.created_at
                    FROM omnigraph.documents d
                    JOIN omnigraph.users u ON u.user_id = d.uploaded_by
                    WHERE to_tsvector('english', d.title || ' ' || d.content)
                          @@ plainto_tsquery('english', %s)
                      AND d.is_archived = FALSE
                      {sensitivity_clause}
                    ORDER BY search_rank DESC
                    LIMIT %s
                    """,
                    params,
                )
                columns = ["document_id", "title", "source_type", "sensitivity_level",
                           "score", "summary", "author", "created_at"]
                results = []
                for row in cur.fetchall():
                    r = dict(zip(columns, row))
                    r["search_type"] = "fulltext"
                    r["score"] = float(r["score"]) if r["score"] else 0.0
                    results.append(r)
                return results
        except psycopg2.Error as exc:
            logger.error("Full-text search failed: %s", exc)
            try:
                self.db.conn.rollback()
            except Exception:
                pass
            return []

    def vector_similarity_search(self, query: str, limit: int = 10,
                                 sensitivity_filter: Optional[List[str]] = None) -> List[Dict]:
        global _semantic_warned
        if not _embedder_available():
            if not _semantic_warned:
                logger.warning("Semantic search disabled (voyageai/VOYAGE_API_KEY not configured); "
                               "skipping vector search for the rest of this session.")
                _semantic_warned = True
            return []
        try:
            query_vector = self._generate_query_embedding(query)
            query_str = "[" + ",".join(str(v) for v in query_vector) + "]"
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.document_id, d.title, d.source_type, d.sensitivity_level,
                           1 - (e.vector <=> %s::vector) AS score,
                           LEFT(d.summary, 200) AS summary,
                           u.full_name AS author, d.created_at
                    FROM omnigraph.embeddings e
                    JOIN omnigraph.documents d ON d.document_id = e.source_id
                    JOIN omnigraph.users u ON u.user_id = d.uploaded_by
                    WHERE e.source_type = 'document'
                      AND d.is_archived = FALSE
                    ORDER BY e.vector <=> %s::vector
                    LIMIT %s
                    """,
                    (query_str, query_str, limit),
                )
                columns = ["document_id", "title", "source_type", "sensitivity_level",
                           "score", "summary", "author", "created_at"]
                results = []
                for row in cur.fetchall():
                    r = dict(zip(columns, row))
                    r["search_type"] = "semantic"
                    r["score"] = float(r["score"]) if r["score"] else 0.0
                    results.append(r)
                return results
        except (ImportError, EnvironmentError):
            return []
        except psycopg2.Error as exc:
            logger.error("Vector similarity search failed: %s", exc)
            try:
                self.db.conn.rollback()
            except Exception:
                pass
            return []

    def graph_traverse(
        self, parsed_query: Dict, limit: int = 10,
    ) -> List[Dict]:
        terms = parsed_query.get("terms", [])
        if not terms:
            return []

        # Bound regex size before querying.
        unique_terms = list(dict.fromkeys(terms))[:10]
        max_term_length = 64
        max_total_length = 256

        safe_terms: List[str] = []
        total_length = 0
        for t in unique_terms:
            if not t:
                continue
            if len(t) > max_term_length:
                logger.debug(
                    "Skipping overly long term in graph_traverse: %r (len=%d)",
                    t[:max_term_length],
                    len(t),
                )
                continue
            total_length += len(t)
            if total_length > max_total_length:
                logger.warning(
                    "Graph traversal term length budget exceeded; using first %d terms.",
                    len(safe_terms),
                )
                break
            safe_terms.append(t)

        if not safe_terms:
            return []

        term_pattern = "|".join(re.escape(t) for t in safe_terms)
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    WITH matched_entities AS (
                        SELECT entity_id, name, entity_type
                        FROM omnigraph.entities WHERE name ~* %s
                    ),
                    related_docs AS (
                        SELECT de.document_id, de.relevance AS score, 'direct_entity_link' AS traversal_type
                        FROM matched_entities me
                        JOIN omnigraph.document_entities de ON de.entity_id = me.entity_id
                        UNION ALL
                        SELECT de.document_id, de.relevance * r.strength AS score, 'relationship_hop' AS traversal_type
                        FROM matched_entities me
                        JOIN omnigraph.relations r ON r.source_entity_id = me.entity_id
                        JOIN omnigraph.document_entities de ON de.entity_id = r.target_entity_id
                    )
                    SELECT d.document_id, d.title, d.source_type, d.sensitivity_level,
                           MAX(rd.score) AS score, LEFT(d.summary, 200) AS summary,
                           u.full_name AS author, d.created_at
                    FROM related_docs rd
                    JOIN omnigraph.documents d ON d.document_id = rd.document_id
                    JOIN omnigraph.users u ON u.user_id = d.uploaded_by
                    WHERE d.is_archived = FALSE
                    GROUP BY d.document_id, d.title, d.source_type,
                             d.sensitivity_level, d.summary, u.full_name, d.created_at
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (term_pattern, limit),
                )
                columns = ["document_id", "title", "source_type", "sensitivity_level",
                           "score", "summary", "author", "created_at"]
                results = []
                for row in cur.fetchall():
                    r = dict(zip(columns, row))
                    r["search_type"] = "graph"
                    r["score"] = float(r["score"]) if r["score"] else 0.0
                    results.append(r)
                return results
        except psycopg2.Error as exc:
            logger.error("Graph traversal failed: %s", exc)
            return []

    def find_experts(self, concept_name: str, limit: int = 5) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.user_id, u.full_name, u.department, u.title,
                           COUNT(DISTINCT d.document_id) AS doc_count,
                           ROUND(AVG(dc.relevance_score), 3) AS avg_relevance,
                           ROUND(COUNT(DISTINCT d.document_id) * AVG(dc.relevance_score) * 10, 2) AS expertise_score
                    FROM omnigraph.users u
                    JOIN omnigraph.documents d ON d.uploaded_by = u.user_id
                    JOIN omnigraph.document_concepts dc ON dc.document_id = d.document_id
                    JOIN omnigraph.concepts c ON c.concept_id = dc.concept_id
                    WHERE LOWER(c.name) = LOWER(%s) AND u.is_active = TRUE
                    GROUP BY u.user_id, u.full_name, u.department, u.title
                    ORDER BY expertise_score DESC
                    LIMIT %s
                    """,
                    (concept_name, limit),
                )
                columns = ["user_id", "full_name", "department", "title",
                           "doc_count", "avg_relevance", "expertise_score"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Expert search failed: %s", exc)
            return []

    def find_related_concepts(self, concept_name: str) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    WITH target_concept AS (
                        SELECT concept_id FROM omnigraph.concepts
                        WHERE LOWER(name) = LOWER(%s) LIMIT 1
                    ),
                    hierarchy_related AS (
                        SELECT child_concept_id AS related_id, 'child' AS relation
                        FROM omnigraph.concept_hierarchy ch, target_concept tc
                        WHERE ch.parent_concept_id = tc.concept_id
                        UNION ALL
                        SELECT parent_concept_id, 'parent'
                        FROM omnigraph.concept_hierarchy ch, target_concept tc
                        WHERE ch.child_concept_id = tc.concept_id
                    ),
                    cooccurring AS (
                        SELECT dc2.concept_id AS related_id, 'co_occurrence' AS relation
                        FROM target_concept tc
                        JOIN omnigraph.document_concepts dc1 ON dc1.concept_id = tc.concept_id
                        JOIN omnigraph.document_concepts dc2
                            ON dc2.document_id = dc1.document_id AND dc2.concept_id != tc.concept_id
                    ),
                    all_related AS (
                        SELECT related_id, relation FROM hierarchy_related
                        UNION ALL SELECT related_id, relation FROM cooccurring
                    )
                    SELECT c.name, c.domain,
                           STRING_AGG(DISTINCT ar.relation, ', ') AS relationship_types,
                           COUNT(*) AS connection_strength
                    FROM all_related ar
                    JOIN omnigraph.concepts c ON c.concept_id = ar.related_id
                    GROUP BY c.concept_id, c.name, c.domain
                    ORDER BY connection_strength DESC
                    """,
                    (concept_name,),
                )
                columns = ["name", "domain", "relationship_types", "connection_strength"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Related concepts search failed: %s", exc)
            return []

    def get_entity_documents(self, entity_name: str, limit: int = 10) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.document_id, d.title, d.source_type, de.relevance, de.mention_count,
                           u.full_name AS author, d.created_at
                    FROM omnigraph.entities e
                    JOIN omnigraph.document_entities de ON de.entity_id = e.entity_id
                    JOIN omnigraph.documents d ON d.document_id = de.document_id
                    JOIN omnigraph.users u ON u.user_id = d.uploaded_by
                    WHERE LOWER(e.name) = LOWER(%s) AND d.is_archived = FALSE
                    ORDER BY de.relevance DESC
                    LIMIT %s
                    """,
                    (entity_name, limit),
                )
                columns = ["document_id", "title", "source_type", "relevance",
                           "mention_count", "author", "created_at"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Entity document search failed: %s", exc)
            return []

    @staticmethod
    def parse_query(query: str) -> Dict:
        words = re.findall(r"\b\w+\b", query.lower())
        terms = [w for w in words if w not in _STOP_WORDS and len(w) > 2]

        intent = "search"
        ql = query.lower()
        if any(w in ql for w in ["expert", "who knows", "specialist"]):
            intent = "find_expert"
        elif any(w in ql for w in ["related", "similar", "like"]):
            intent = "find_related"
        elif any(w in ql for w in ["path", "connection", "between"]):
            intent = "find_path"
        elif any(w in ql for w in ["trend", "history", "over time"]):
            intent = "analytics"

        return {"terms": terms, "intent": intent, "original_query": query}

    @staticmethod
    def rank_results(results: List[Dict]) -> List[Dict]:
        doc_scores: Dict[int, Dict] = {}
        for result in results:
            doc_id = result.get("document_id")
            if doc_id is None:
                continue
            search_type = result.get("search_type", "fulltext")
            weight = _RANK_WEIGHTS.get(search_type, 1.0)
            weighted = result.get("score", 0.0) * weight
            if doc_id in doc_scores:
                doc_scores[doc_id]["score"] += weighted
                doc_scores[doc_id]["sources"].add(search_type)
            else:
                doc_scores[doc_id] = {
                    **result,
                    "score": weighted,
                    "sources": {search_type},
                }
        ranked = list(doc_scores.values())
        for r in ranked:
            r["sources"] = list(r.get("sources", []))
        ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
        return ranked

    def _hybrid_search(
        self,
        query: str,
        parsed: Dict,
        limit: int,
        sensitivity_filter: Optional[List[str]] = None,
    ) -> List[Dict]:
        
        # Fetch extra candidates before ranking.
        per_source_limit = max(limit * 3, limit)
        per_source_limit = min(per_source_limit, 50)

        all_results: List[Dict] = []
        all_results.extend(self.fulltext_search(query, per_source_limit, sensitivity_filter))
        all_results.extend(self.vector_similarity_search(query, per_source_limit))
        all_results.extend(self.graph_traverse(parsed, per_source_limit))
        return all_results

    def _log_query(
        self, query_text: str, query_type: str, results_count: int, execution_ms: int,
    ) -> None:
        if self.user_id is None:
            return
        db_query_type = _QUERY_TYPE_MAP.get(query_type, "keyword_search")
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.query_logs
                        (user_id, query_text, query_type, results_count, execution_ms)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self.user_id, query_text, db_query_type, results_count, execution_ms),
                )
            self.db.conn.commit()
        except psycopg2.Error as exc:
            logger.warning("Failed to log query: %s", exc)
            try:
                self.db.conn.rollback()
            except Exception:
                pass

    @staticmethod
    def _generate_query_embedding(query: str) -> List[float]:
        return generate_embedding(query, input_type="query")


if __name__ == "__main__":
    try:
        from .ingestion_pipeline import DatabaseConnection
    except ImportError:
        from ingestion_pipeline import DatabaseConnection

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db = DatabaseConnection()
    db.connect()
    engine = SemanticQueryEngine(db, user_id=8)

    print("=== Full-Text Search: 'machine learning' ===")
    for r in engine.search("machine learning neural network", strategy="fulltext"):
        print(f"  [{r['score']:.3f}] {r['title']}")

    print("\n=== Find Experts: 'Deep Learning' ===")
    for e in engine.find_experts("Deep Learning"):
        print(f"  {e['full_name']} ({e['department']}) - score={e['expertise_score']}")

    print("\n=== Related Concepts: 'Machine Learning' ===")
    for c in engine.find_related_concepts("Machine Learning"):
        print(f"  {c['name']} [{c['domain']}] via {c['relationship_types']}")

    print("\n=== Hybrid Search ===")
    for r in engine.search("kubernetes cloud deployment", strategy="hybrid"):
        print(f"  [{r['score']:.3f}] {r['title']} (via {r.get('sources', [])})")

    db.disconnect()
