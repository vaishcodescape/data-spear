import logging
from typing import Dict, List, Optional

import psycopg2
logger = logging.getLogger("omnigraph.graph_builder")

_GRAPH_STATS_SQL = """
SELECT
    (SELECT COUNT(*) FROM omnigraph.entities) AS total_entities,
    (SELECT COUNT(*) FROM omnigraph.relations) AS total_relations,
    (SELECT COUNT(*) FROM omnigraph.concepts) AS total_concepts,
    (SELECT COUNT(*) FROM omnigraph.documents) AS total_documents,
    (SELECT COUNT(*) FROM omnigraph.taxonomy) AS total_taxonomy_nodes
"""
_ENTITIES_BY_TYPE_SQL = """
SELECT entity_type, COUNT(*) FROM omnigraph.entities
GROUP BY entity_type ORDER BY COUNT(*) DESC
"""
_RELATIONS_BY_TYPE_SQL = """
SELECT relation_type, COUNT(*) FROM omnigraph.relations
GROUP BY relation_type ORDER BY COUNT(*) DESC
"""


# Maintains graph entities, relations, taxonomy, and concepts.
class KnowledgeGraphBuilder:

    def __init__(self, db_connection):
        self.db = db_connection

    def add_entity_node(
        self,
        name: str,
        entity_type: str,
        description: Optional[str] = None,
        confidence: float = 0.800,
    ) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_id FROM omnigraph.entities
                    WHERE LOWER(name) = LOWER(%s) AND entity_type = %s LIMIT 1
                    """,
                    (name, entity_type),
                )
                row = cur.fetchone()
                if row:
                    logger.info("Entity '%s' already exists (id=%d).", name, row[0])
                    return row[0]

                cur.execute(
                    """
                    INSERT INTO omnigraph.entities (name, entity_type, description, confidence)
                    VALUES (%s, %s, %s, %s)
                    RETURNING entity_id
                    """,
                    (name, entity_type, description, confidence),
                )
                entity_id = cur.fetchone()[0]
            self.db.conn.commit()
            logger.info("Added entity node '%s' (id=%d).", name, entity_id)
            return entity_id

        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to add entity '%s': %s", name, exc)
            return None

    def remove_entity_node(self, entity_id: int) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM omnigraph.entities WHERE entity_id = %s",
                    (entity_id,),
                )
                deleted = cur.rowcount > 0
            self.db.conn.commit()
            if deleted:
                logger.info("Removed entity node id=%d.", entity_id)
            return deleted
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to remove entity %d: %s", entity_id, exc)
            return False

    def update_entity_node(
        self,
        entity_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> bool:
        if all(v is None for v in (name, description, confidence)):
            logger.warning("update_entity_node: no fields to update for entity_id=%s", entity_id)
            return False
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT name, entity_type, description, confidence FROM omnigraph.entities WHERE entity_id = %s",
                    (entity_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                cur_name, entity_type, cur_desc, cur_conf = row
                new_name = name if name is not None else cur_name
                new_desc = description if description is not None else cur_desc
                new_conf = confidence if confidence is not None else cur_conf
                cur.execute(
                    """
                    UPDATE omnigraph.entities
                    SET name = %s, description = %s, confidence = %s
                    WHERE entity_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM omnigraph.entities e2
                          WHERE e2.entity_id <> %s
                            AND LOWER(e2.name) = LOWER(%s)
                            AND e2.entity_type = %s
                      )
                    """,
                    (new_name, new_desc, new_conf, entity_id, entity_id, new_name, entity_type),
                )
                updated = cur.rowcount > 0
            self.db.conn.commit()
            if updated:
                logger.info("Updated entity id=%s.", entity_id)
            return updated
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to update entity %d: %s", entity_id, exc)
            return False

    def add_relationship(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relation_type: str,
        strength: float = 1.0,
        description: Optional[str] = None,
        source_document_id: Optional[int] = None,
    ) -> Optional[int]:
        if source_entity_id == target_entity_id:
            logger.warning("Cannot create self-referencing relationship.")
            return None
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.relations
                        (source_entity_id, target_entity_id, relation_type,
                         strength, description, source_document_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING relation_id
                    """,
                    (
                        source_entity_id, target_entity_id, relation_type,
                        strength, description, source_document_id,
                    ),
                )
                relation_id = cur.fetchone()[0]
            self.db.conn.commit()
            logger.info(
                "Added relationship %d -[%s]-> %d (id=%d).",
                source_entity_id, relation_type, target_entity_id, relation_id,
            )
            return relation_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to add relationship: %s", exc)
            return None

    def remove_relationship(self, relation_id: int) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM omnigraph.relations WHERE relation_id = %s",
                    (relation_id,),
                )
                deleted = cur.rowcount > 0
            self.db.conn.commit()
            if deleted:
                logger.info("Removed relation id=%d.", relation_id)
            return deleted
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to remove relation %d: %s", relation_id, exc)
            return False

    def map_document_entity(
        self,
        document_id: int,
        entity_id: int,
        relevance: float = 1.0,
        mention_count: int = 1,
    ) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.document_entities
                        (document_id, entity_id, relevance, mention_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (document_id, entity_id) DO UPDATE
                        SET relevance = EXCLUDED.relevance,
                            mention_count = EXCLUDED.mention_count
                    """,
                    (document_id, entity_id, relevance, mention_count),
                )
            self.db.conn.commit()
            return True
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to map document %d to entity %d: %s",
                         document_id, entity_id, exc)
            return False

    def add_taxonomy_node(
        self,
        name: str,
        parent_id: Optional[int] = None,
        domain: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.taxonomy (name, parent_id, domain, description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING taxonomy_id
                    """,
                    (name, parent_id, domain, description),
                )
                taxonomy_id = cur.fetchone()[0]
            self.db.conn.commit()
            logger.info("Added taxonomy node '%s' (id=%d).", name, taxonomy_id)
            return taxonomy_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to add taxonomy node '%s': %s", name, exc)
            return None

    def get_taxonomy_tree(self, root_name: Optional[str] = None) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                if root_name:
                    cur.execute(
                        """
                        WITH RECURSIVE tree AS (
                            SELECT taxonomy_id, name, parent_id, level, domain,
                                   ARRAY[name]::TEXT[] AS path
                            FROM omnigraph.taxonomy
                            WHERE LOWER(name) = LOWER(%s)
                            UNION ALL
                            SELECT t.taxonomy_id, t.name, t.parent_id, t.level, t.domain,
                                   tree.path || t.name
                            FROM omnigraph.taxonomy t
                            JOIN tree ON t.parent_id = tree.taxonomy_id
                        )
                        SELECT * FROM tree ORDER BY path
                        """,
                        (root_name,),
                    )
                else:
                    cur.execute(
                        """
                        WITH RECURSIVE tree AS (
                            SELECT taxonomy_id, name, parent_id, level, domain,
                                   ARRAY[name]::TEXT[] AS path
                            FROM omnigraph.taxonomy
                            WHERE parent_id IS NULL
                            UNION ALL
                            SELECT t.taxonomy_id, t.name, t.parent_id, t.level, t.domain,
                                   tree.path || t.name
                            FROM omnigraph.taxonomy t
                            JOIN tree ON t.parent_id = tree.taxonomy_id
                        )
                        SELECT * FROM tree ORDER BY path
                        """
                    )
                columns = ["taxonomy_id", "name", "parent_id", "level", "domain", "path"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Failed to retrieve taxonomy tree: %s", exc)
            return []

    def add_concept_link(
        self,
        parent_concept_id: int,
        child_concept_id: int,
        relationship_type: str = "is_parent_of",
    ) -> bool:
        if parent_concept_id == child_concept_id:
            logger.warning("Cannot create self-referencing concept link.")
            return False
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.concept_hierarchy
                        (parent_concept_id, child_concept_id, relationship_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (parent_concept_id, child_concept_id) DO NOTHING
                    """,
                    (parent_concept_id, child_concept_id, relationship_type),
                )
            self.db.conn.commit()
            return True
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to add concept link: %s", exc)
            return False

    def get_concept_hierarchy(self, root_concept_name: str) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    WITH RECURSIVE hierarchy AS (
                        SELECT c.concept_id, c.name, c.domain,
                               NULL::VARCHAR AS parent_name, 0 AS depth
                        FROM omnigraph.concepts c
                        WHERE LOWER(c.name) = LOWER(%s)
                        UNION ALL
                        SELECT child.concept_id, child.name, child.domain,
                               h.name AS parent_name, h.depth + 1
                        FROM hierarchy h
                        JOIN omnigraph.concept_hierarchy ch ON ch.parent_concept_id = h.concept_id
                        JOIN omnigraph.concepts child ON child.concept_id = ch.child_concept_id
                        WHERE h.depth < 10
                    )
                    SELECT * FROM hierarchy ORDER BY depth, name
                    """,
                    (root_concept_name,),
                )
                columns = ["concept_id", "name", "domain", "parent_name", "depth"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Failed to retrieve concept hierarchy: %s", exc)
            return []

    def get_entity_neighborhood(
        self, entity_id: int, max_depth: int = 2,
    ) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    WITH RECURSIVE neighborhood AS (
                        SELECT r.target_entity_id AS entity_id, e.name, e.entity_type,
                               r.relation_type, r.strength, 1 AS depth,
                               ARRAY[%s, r.target_entity_id] AS visited
                        FROM omnigraph.relations r
                        JOIN omnigraph.entities e ON e.entity_id = r.target_entity_id
                        WHERE r.source_entity_id = %s
                        UNION ALL
                        SELECT r.target_entity_id, e.name, e.entity_type,
                               r.relation_type, r.strength, n.depth + 1,
                               n.visited || r.target_entity_id
                        FROM neighborhood n
                        JOIN omnigraph.relations r ON r.source_entity_id = n.entity_id
                        JOIN omnigraph.entities e ON e.entity_id = r.target_entity_id
                        WHERE n.depth < %s AND NOT (r.target_entity_id = ANY(n.visited))
                    )
                    SELECT DISTINCT entity_id, name, entity_type, relation_type, strength, depth
                    FROM neighborhood ORDER BY depth, strength DESC
                    """,
                    (entity_id, entity_id, max_depth),
                )
                columns = ["entity_id", "name", "entity_type", "relation_type", "strength", "depth"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Failed to get entity neighborhood: %s", exc)
            return []

    def detect_duplicate_nodes(self) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e1.entity_id, e1.name, e2.entity_id, e2.name
                    FROM omnigraph.entities e1
                    JOIN omnigraph.entities e2
                        ON e1.entity_id < e2.entity_id
                        AND e1.entity_type = e2.entity_type
                        AND LOWER(e1.name) = LOWER(e2.name)
                    ORDER BY e1.name
                    """
                )
                columns = ["entity_id_1", "name_1", "entity_id_2", "name_2"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Duplicate detection failed: %s", exc)
            return []

    def get_graph_stats(self) -> Dict:
        stats: Dict = {}
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(_GRAPH_STATS_SQL)
                row = cur.fetchone()
                if row:
                    stats["total_entities"] = row[0]
                    stats["total_relations"] = row[1]
                    stats["total_concepts"] = row[2]
                    stats["total_documents"] = row[3]
                    stats["total_taxonomy_nodes"] = row[4]

                cur.execute(_ENTITIES_BY_TYPE_SQL)
                stats["entities_by_type"] = dict(cur.fetchall())

                cur.execute(_RELATIONS_BY_TYPE_SQL)
                stats["relations_by_type"] = dict(cur.fetchall())
            return stats
        except psycopg2.Error as exc:
            logger.error("Failed to get graph stats: %s", exc)
            return stats

    def build_graph(self, extractor=None) -> Dict:
        """
        Build / rebuild the knowledge graph.

        If an ``extractor`` (EntityRelationExtractor) is supplied, every document
        that has no entity links yet is processed automatically so the graph is
        always up-to-date with all ingested content.
        """
        logger.info("Starting knowledge graph construction.")
        processed_count = 0

        if extractor is not None:
            try:
                with self.db.conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.document_id
                        FROM omnigraph.documents d
                        LEFT JOIN omnigraph.document_entities de
                               ON de.document_id = d.document_id
                        WHERE d.is_archived = FALSE
                          AND de.document_id IS NULL
                        ORDER BY d.document_id
                        """
                    )
                    unprocessed = [row[0] for row in cur.fetchall()]

                logger.info(
                    "Found %d documents without entity extractions — processing now.",
                    len(unprocessed),
                )
                for doc_id in unprocessed:
                    try:
                        extractor.process_document(doc_id)
                        processed_count += 1
                    except Exception as exc:
                        logger.error(
                            "Extraction failed for document %d: %s", doc_id, exc,
                        )
            except psycopg2.Error as exc:
                logger.error("Failed to query unprocessed documents: %s", exc)

        duplicates = self.detect_duplicate_nodes()
        if duplicates:
            logger.warning("Found %d potential duplicate entity pairs.", len(duplicates))

        stats = self.get_graph_stats()
        logger.info(
            "Graph build complete: %d entities, %d relations, %d concepts, %d documents. "
            "(%d documents newly extracted)",
            stats.get("total_entities", 0), stats.get("total_relations", 0),
            stats.get("total_concepts", 0), stats.get("total_documents", 0),
            processed_count,
        )
        return {
            "stats": stats,
            "duplicates_detected": len(duplicates),
            "duplicate_pairs": duplicates,
            "documents_newly_extracted": processed_count,
        }


if __name__ == "__main__":
    try:
        from .ingestion_pipeline import DatabaseConnection
    except ImportError:
        from ingestion_pipeline import DatabaseConnection

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db = DatabaseConnection()
    db.connect()
    builder = KnowledgeGraphBuilder(db)

    result = builder.build_graph()
    print("\n=== Knowledge Graph Statistics ===")
    for key, value in result["stats"].items():
        print(f"  {key}: {value}")
    if result["duplicates_detected"] > 0:
        print(f"\n  WARNING: {result['duplicates_detected']} duplicate pairs found!")

    print("\n=== Taxonomy Tree ===")
    for node in builder.get_taxonomy_tree():
        indent = "  " * node["level"]
        print(f"  {indent}├── {node['name']} (level={node['level']})")

    print("\n=== Concept Hierarchy: Machine Learning ===")
    for node in builder.get_concept_hierarchy("Machine Learning"):
        indent = "  " * node["depth"]
        parent = f" ← {node['parent_name']}" if node["parent_name"] else ""
        print(f"  {indent}├── {node['name']}{parent}")

    db.disconnect()
