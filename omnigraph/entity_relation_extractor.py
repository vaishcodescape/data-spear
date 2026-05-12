import json
import logging
import re
from typing import Dict, List, Optional, Set

import psycopg2  # type: ignore[import-untyped]
from psycopg2.extras import execute_values

from .config import settings

logger = logging.getLogger("omnigraph.extractor")

# ── Keyword fallback dictionaries ────────────────────────────────────────────

TECHNOLOGY_KEYWORDS = {
    "Kubernetes", "Docker", "TensorFlow", "PyTorch", "BERT", "GPT",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "Spark",
    "Hadoop", "AWS", "Azure", "GCP", "Istio", "ArgoCD", "Helm",
    "Terraform", "Ansible", "Jenkins", "GraphQL", "REST", "gRPC",
    "React", "Angular", "Vue", "Node.js", "Python", "Java", "Go",
    "Rust", "TypeScript", "JavaScript", "CUDA", "OpenAI", "LangChain",
    "Transformer", "LSTM", "CNN", "RNN", "GAN", "VAE", "GraphSAGE",
    "Prophet", "Airflow", "MLflow", "Kubeflow", "PagerDuty",
    "Federated Learning", "OAuth 2.0", "Zero Trust",
}

ORGANIZATION_KEYWORDS = {
    "Google", "Microsoft", "Amazon", "Meta", "Apple", "Netflix",
    "IBM", "Oracle", "SAP", "Salesforce", "VMware", "Red Hat",
    "Databricks", "Snowflake", "Confluent", "HashiCorp", "NVIDIA",
    "Intel", "AMD", "Qualcomm", "NIST", "IEEE", "ACM", "W3C",
}

STANDARD_KEYWORDS = {
    "GDPR", "CCPA", "HIPAA", "SOC2", "ISO 27001", "PCI DSS",
    "NIST 800-53", "OWASP", "CIS", "ITIL", "TOGAF", "COBIT",
}

CONCEPT_DOMAINS = {
    "machine learning": "AI", "deep learning": "AI",
    "natural language processing": "AI", "computer vision": "AI",
    "knowledge graph": "AI", "neural network": "AI", "transfer learning": "AI",
    "reinforcement learning": "AI", "cybersecurity": "Security", "zero trust": "Security",
    "encryption": "Security", "threat detection": "Security",
    "cloud computing": "Infrastructure", "containerization": "Infrastructure",
    "microservices": "Engineering", "api design": "Engineering",
    "devops": "Operations", "ci/cd": "Operations", "data governance": "Compliance",
    "compliance": "Compliance", "predictive analytics": "Analytics", "supply chain": "Business",
    "data pipeline": "Engineering", "graph neural network": "AI", "federated learning": "AI",
    "privacy": "Compliance",
}

_REL_PATTERNS_RAW = [
    (r"(\w[\w\s]*?)\s+(?:is developed by|was developed by|created by)\s+(\w[\w\s]*)", "developed_by"),
    (r"(\w[\w\s]*?)\s+(?:works for|employed at|works at)\s+(\w[\w\s]*)", "works_for"),
    (r"(\w[\w\s]*?)\s+(?:collaborates with|partners with)\s+(\w[\w\s]*)", "collaborates_with"),
    (r"(\w[\w\s]*?)\s+(?:depends on|requires|relies on)\s+(\w[\w\s]*)", "depends_on"),
    (r"(\w[\w\s]*?)\s+(?:is part of|belongs to)\s+(\w[\w\s]*)", "part_of"),
    (r"(\w[\w\s]*?)\s+(?:competes with|rivals)\s+(\w[\w\s]*)", "competitor_of"),
    (r"(\w[\w\s]*?)\s+(?:uses|utilizes|leverages|employs)\s+(\w[\w\s]*)", "uses"),
    (r"(\w[\w\s]*?)\s+(?:manages|oversees|leads)\s+(\w[\w\s]*)", "manages"),
    (r"(\w[\w\s]*?)\s+(?:is located in|based in|headquartered in)\s+(\w[\w\s]*)", "located_in"),
]
RELATIONSHIP_PATTERNS = [(re.compile(p, re.IGNORECASE), t) for p, t in _REL_PATTERNS_RAW]

PERSON_PATTERN = re.compile(
    r"\b((?:Dr\.|Prof\.|Mr\.|Ms\.|Mrs\.)\s+[A-Z][a-z]+\s+[A-Z][a-z]+)\b"
)

_VALID_ENTITY_TYPES = {"person", "organization", "technology", "standard", "location", "other"}
_VALID_DOMAINS = {"AI", "Security", "Infrastructure", "Engineering", "Operations",
                  "Compliance", "Analytics", "Business", "Other"}

_LLM_EXTRACTION_PROMPT = """\
You are an expert information extraction system for an enterprise knowledge graph.

Extract ALL entities, concepts, and relationships from the text below.

Return ONLY a valid JSON object — no markdown, no explanation:
{{
  "entities": [
    {{
      "name": "exact name as mentioned in text",
      "entity_type": "person | organization | technology | standard | location | other",
      "description": "one-line description",
      "confidence": 0.85
    }}
  ],
  "concepts": [
    {{
      "name": "concept name",
      "domain": "AI | Security | Infrastructure | Engineering | Operations | Compliance | Analytics | Business | Other"
    }}
  ],
  "relationships": [
    {{
      "source": "source entity name (must match an entity above)",
      "target": "target entity name (must match an entity above)",
      "relation_type": "uses | developed_by | works_for | depends_on | part_of | collaborates_with | manages | located_in | competitor_of | other",
      "strength": 0.8
    }}
  ]
}}

Rules:
- Only extract entities clearly mentioned in the text.
- confidence: 0.7 (implied/unclear) → 1.0 (explicitly named with full context).
- Only include relationships explicitly stated — not inferred.
- strength: 0.5 (implied) → 1.0 (explicitly stated).
- Relationships must have both source and target present in the entities list.

Text:
{text}"""


class EntityRelationExtractor:
    """
    Extracts entities, concepts, and relationships from document text.

    Primary strategy: Claude Haiku LLM extraction (when ANTHROPIC_API_KEY is set).
    Fallback strategy: regex + keyword matching (always available).
    Both results are merged so neither source is silently dropped.
    """

    def __init__(self, db_connection, use_llm: bool = True):
        self.db = db_connection
        self._use_llm = use_llm and bool(settings.anthropic_api_key)
        self._llm_client = None

        if self._use_llm:
            try:
                import anthropic
                self._llm_client = anthropic.Anthropic()
                logger.info("LLM entity extraction enabled (claude-haiku-4-5).")
            except ImportError:
                self._use_llm = False
                logger.warning("anthropic not installed; using keyword extraction only.")

    # ── Public extraction methods (keyword-based, always available) ───────────

    def extract_entities(self, text: str) -> List[Dict]:
        entities = []
        entities.extend(self._match_keywords(text, TECHNOLOGY_KEYWORDS, "technology"))
        entities.extend(self._match_keywords(text, ORGANIZATION_KEYWORDS, "organization"))
        entities.extend(self._match_keywords(text, STANDARD_KEYWORDS, "standard"))
        entities.extend(self._extract_persons(text))
        logger.debug("Keyword extraction: %d entities.", len(entities))
        return entities

    def extract_concepts(self, text: str) -> List[Dict]:
        text_lower = text.lower()
        concepts = []
        for concept, domain in CONCEPT_DOMAINS.items():
            count = text_lower.count(concept)
            if count > 0:
                relevance = min(1.0, count * 0.15)
                concepts.append({
                    "name": concept.title(),
                    "domain": domain,
                    "relevance_score": round(relevance, 3),
                    "mention_count": count,
                })
        concepts.sort(key=lambda c: c["relevance_score"], reverse=True)
        logger.debug("Keyword extraction: %d concepts.", len(concepts))
        return concepts

    def extract_relationships(self, text: str, entities: List[Dict]) -> List[Dict]:
        entity_names = {e["name"] for e in entities}
        relationships = []

        for pattern, rel_type in RELATIONSHIP_PATTERNS:
            for match in pattern.finditer(text):
                source = match.group(1).strip()
                target = match.group(2).strip()
                source_match = self._fuzzy_match(source, entity_names)
                target_match = self._fuzzy_match(target, entity_names)
                if source_match and target_match and source_match != target_match:
                    relationships.append({
                        "source": source_match,
                        "target": target_match,
                        "relation_type": rel_type,
                        "strength": 0.750,
                    })

        seen: set = set()
        unique = []
        for rel in relationships:
            key = (rel["source"], rel["target"], rel["relation_type"])
            if key not in seen:
                seen.add(key)
                unique.append(rel)
        logger.debug("Keyword extraction: %d relationships.", len(unique))
        return unique

    # ── Primary entry point ───────────────────────────────────────────────────

    def process_document(self, document_id: int) -> Dict:
        """Extract and store entities, concepts, and relationships for a document."""
        with self.db.conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM omnigraph.documents WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
        if not row:
            logger.error("Document %d not found.", document_id)
            return {"entities": [], "concepts": [], "relationships": []}

        content = row[0]

        if self._use_llm:
            entities, concepts, relationships = self._extract_merged(content)
        else:
            entities = self.extract_entities(content)
            concepts = self.extract_concepts(content)
            relationships = self.extract_relationships(content, entities)

        self._store_entities(entities, document_id)
        self._store_concepts(concepts, document_id)
        self._store_relationships(relationships, document_id)

        logger.info(
            "Document %d: stored %d entities, %d concepts, %d relationships.",
            document_id, len(entities), len(concepts), len(relationships),
        )
        return {"entities": entities, "concepts": concepts, "relationships": relationships}

    # ── LLM extraction ────────────────────────────────────────────────────────

    def _extract_with_llm(self, text: str) -> Dict:
        """Call Claude Haiku to extract structured entities/concepts/relationships."""
        truncated = text[:6000]
        prompt = _LLM_EXTRACTION_PROMPT.format(text=truncated)

        response = self._llm_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if the model added them
        if "```" in raw:
            raw = re.sub(r"```(?:json)?\n?", "", raw).strip()
            raw = re.sub(r"\n?```", "", raw).strip()

        return json.loads(raw)

    def _extract_merged(self, text: str):
        """
        Run LLM extraction and merge with keyword results.
        Falls back to keyword-only if LLM raises any exception.
        Returns (entities, concepts, relationships).
        """
        try:
            llm_data = self._extract_with_llm(text)
            entities = self._normalize_llm_entities(llm_data.get("entities", []), text)
            concepts = self._normalize_llm_concepts(llm_data.get("concepts", []), text)

            # Merge keyword entities so well-known tech terms are never missed
            kw_entities = self.extract_entities(text)
            seen_names = {e["name"].lower() for e in entities}
            for e in kw_entities:
                if e["name"].lower() not in seen_names:
                    entities.append(e)
                    seen_names.add(e["name"].lower())

            # Merge keyword concepts
            kw_concepts = self.extract_concepts(text)
            seen_concepts = {c["name"].lower() for c in concepts}
            for c in kw_concepts:
                if c["name"].lower() not in seen_concepts:
                    concepts.append(c)
                    seen_concepts.add(c["name"].lower())

            # LLM relationships, supplemented by regex
            relationships = self._normalize_llm_relationships(
                llm_data.get("relationships", []), entities,
            )
            rel_keys = {(r["source"], r["target"], r["relation_type"]) for r in relationships}
            for r in self.extract_relationships(text, entities):
                key = (r["source"], r["target"], r["relation_type"])
                if key not in rel_keys:
                    relationships.append(r)
                    rel_keys.add(key)

            logger.info(
                "LLM+keyword extraction: %d entities, %d concepts, %d relationships.",
                len(entities), len(concepts), len(relationships),
            )
            return entities, concepts, relationships

        except Exception as exc:
            logger.warning(
                "LLM extraction failed (%s). Falling back to keyword extraction.", exc,
            )
            entities = self.extract_entities(text)
            concepts = self.extract_concepts(text)
            relationships = self.extract_relationships(content=text, entities=entities)
            return entities, concepts, relationships

    # ── LLM output normalizers ────────────────────────────────────────────────

    def _normalize_llm_entities(self, raw: List[Dict], text: str) -> List[Dict]:
        result = []
        seen: set = set()
        for e in raw:
            name = (e.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            etype = (e.get("entity_type") or "other").lower().strip()
            if etype not in _VALID_ENTITY_TYPES:
                etype = "other"
            count = len(re.findall(re.escape(name), text, re.IGNORECASE))
            result.append({
                "name": name,
                "entity_type": etype,
                "confidence": round(min(1.0, max(0.0, float(e.get("confidence", 0.8)))), 3),
                "mention_count": max(count, 1),
                "description": (e.get("description") or ""),
                "positions": [],
            })
        return result

    def _normalize_llm_concepts(self, raw: List[Dict], text: str) -> List[Dict]:
        result = []
        seen: set = set()
        for c in raw:
            name = (c.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            domain = (c.get("domain") or "Other").strip()
            if domain not in _VALID_DOMAINS:
                domain = "Other"
            count = len(re.findall(re.escape(name), text, re.IGNORECASE))
            result.append({
                "name": name.title(),
                "domain": domain,
                "relevance_score": round(min(1.0, max(count, 1) * 0.15), 3),
                "mention_count": max(count, 1),
            })
        return result

    def _normalize_llm_relationships(
        self, raw: List[Dict], entities: List[Dict],
    ) -> List[Dict]:
        entity_names = {e["name"] for e in entities}
        result = []
        seen: set = set()
        for r in raw:
            source = (r.get("source") or "").strip()
            target = (r.get("target") or "").strip()
            rel_type = (r.get("relation_type") or "other").strip()

            # Try fuzzy match if exact lookup fails
            if source not in entity_names:
                source = self._fuzzy_match(source, entity_names) or source
            if target not in entity_names:
                target = self._fuzzy_match(target, entity_names) or target

            if source in entity_names and target in entity_names and source != target:
                key = (source, target, rel_type)
                if key not in seen:
                    seen.add(key)
                    result.append({
                        "source": source,
                        "target": target,
                        "relation_type": rel_type,
                        "strength": round(min(1.0, max(0.0, float(r.get("strength", 0.75)))), 3),
                    })
        return result

    # ── DB storage (unchanged from original) ─────────────────────────────────

    def _store_entities(self, entities: List[Dict], document_id: int) -> None:
        if not entities:
            return
        entity_ids = []
        with self.db.conn.cursor() as cur:
            for entity in entities:
                try:
                    cur.execute(
                        """
                        INSERT INTO omnigraph.entities (name, entity_type, confidence)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (name, entity_type) DO UPDATE
                            SET confidence = GREATEST(entities.confidence, EXCLUDED.confidence)
                        RETURNING entity_id
                        """,
                        (entity["name"], entity["entity_type"], entity["confidence"]),
                    )
                    entity_ids.append((cur.fetchone()[0], entity))
                except psycopg2.Error as exc:
                    logger.warning("Entity storage error: %s", exc)
                    continue

            if entity_ids:
                link_rows = [
                    (document_id, eid, ent["confidence"], ent["mention_count"])
                    for eid, ent in entity_ids
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO omnigraph.document_entities
                        (document_id, entity_id, relevance, mention_count)
                    VALUES %s
                    ON CONFLICT (document_id, entity_id) DO UPDATE
                        SET mention_count = EXCLUDED.mention_count,
                            relevance = EXCLUDED.relevance
                    """,
                    link_rows,
                )
        try:
            self.db.conn.commit()
        except psycopg2.Error:
            self.db.conn.rollback()

    def _store_concepts(self, concepts: List[Dict], document_id: int) -> None:
        with self.db.conn.cursor() as cur:
            for concept in concepts:
                try:
                    cur.execute(
                        """
                        INSERT INTO omnigraph.concepts (name, domain)
                        VALUES (%s, %s)
                        ON CONFLICT (name) DO NOTHING
                        RETURNING concept_id
                        """,
                        (concept["name"], concept["domain"]),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(
                            "SELECT concept_id FROM omnigraph.concepts WHERE name = %s",
                            (concept["name"],),
                        )
                        row = cur.fetchone()
                    if row:
                        cur.execute(
                            """
                            INSERT INTO omnigraph.document_concepts
                                (document_id, concept_id, relevance_score, extracted_by)
                            VALUES (%s, %s, %s, 'system')
                            ON CONFLICT (document_id, concept_id) DO UPDATE
                                SET relevance_score = EXCLUDED.relevance_score
                            """,
                            (document_id, row[0], concept["relevance_score"]),
                        )
                except psycopg2.Error as exc:
                    logger.warning("Concept storage error: %s", exc)
                    continue
        try:
            self.db.conn.commit()
        except psycopg2.Error:
            self.db.conn.rollback()

    def _store_relationships(self, relationships: List[Dict], document_id: int) -> None:
        if not relationships:
            return
        name_to_id: Dict[str, int] = {}
        with self.db.conn.cursor() as cur:
            names = {rel["source"] for rel in relationships} | {rel["target"] for rel in relationships}
            for name in names:
                cur.execute(
                    "SELECT entity_id FROM omnigraph.entities WHERE name = %s LIMIT 1",
                    (name,),
                )
                row = cur.fetchone()
                if row:
                    name_to_id[name] = row[0]

            for rel in relationships:
                source_id = name_to_id.get(rel["source"])
                target_id = name_to_id.get(rel["target"])
                if not source_id or not target_id or source_id == target_id:
                    continue
                try:
                    cur.execute(
                        """
                        INSERT INTO omnigraph.relations
                            (source_entity_id, target_entity_id, relation_type,
                             strength, source_document_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (source_id, target_id, rel["relation_type"],
                         rel["strength"], document_id),
                    )
                except psycopg2.Error as exc:
                    logger.warning("Relationship storage error: %s", exc)
                    continue
        try:
            self.db.conn.commit()
        except psycopg2.Error:
            self.db.conn.rollback()

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _match_keywords(text: str, keywords: Set[str], entity_type: str) -> List[Dict]:
        if not text or not keywords:
            return []
        sorted_keywords = sorted(keywords, key=len, reverse=True)
        pattern = re.compile(
            "|".join(re.escape(k) for k in sorted_keywords),
            re.IGNORECASE,
        )
        match_positions: Dict[str, List[int]] = {}
        for m in pattern.finditer(text):
            matched_text = m.group(0)
            canonical = next(
                (k for k in keywords if k.lower() == matched_text.lower()),
                matched_text,
            )
            match_positions.setdefault(canonical, []).append(m.start())

        results: List[Dict] = []
        for keyword, positions in match_positions.items():
            count = len(positions)
            confidence = min(0.995, 0.700 + count * 0.05)
            results.append({
                "name": keyword,
                "entity_type": entity_type,
                "confidence": round(confidence, 3),
                "mention_count": count,
                "positions": positions,
            })
        return results

    @staticmethod
    def _extract_persons(text: str) -> List[Dict]:
        persons = []
        seen: Dict[str, List[int]] = {}
        for match in PERSON_PATTERN.finditer(text):
            name = match.group(1).strip()
            seen.setdefault(name, []).append(match.start())
        for name, positions in seen.items():
            count = len(positions)
            persons.append({
                "name": name,
                "entity_type": "person",
                "confidence": round(min(0.900, 0.600 + count * 0.1), 3),
                "mention_count": count,
                "positions": positions,
            })
        return persons

    @staticmethod
    def _fuzzy_match(candidate: str, known_names: Set[str]) -> Optional[str]:
        candidate_lower = candidate.lower().strip()
        if not candidate_lower or not known_names:
            return None
        lower_map = {name.lower(): name for name in known_names}
        if candidate_lower in lower_map:
            return lower_map[candidate_lower]
        for lower_name, original in lower_map.items():
            if lower_name in candidate_lower or candidate_lower in lower_name:
                return original
        return None

    @staticmethod
    def classify_entity(name: str) -> str:
        if name in TECHNOLOGY_KEYWORDS:
            return "technology"
        if name in ORGANIZATION_KEYWORDS:
            return "organization"
        if name in STANDARD_KEYWORDS:
            return "standard"
        return "other"


if __name__ == "__main__":
    sample_text = """
    Google has developed TensorFlow and BERT for machine learning and
    natural language processing research. Kubernetes, originally created
    by Google, depends on Docker for container orchestration. Microsoft
    Azure competes with AWS in cloud computing. The system uses OAuth 2.0
    for authentication and follows GDPR compliance standards.
    Dr. Sarah Lin leads the NLP research division at the company.
    The platform leverages federated learning techniques to ensure privacy
    while training models across distributed data sources.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    extractor = EntityRelationExtractor(db_connection=None)

    print("=== Entity Extraction ===")
    entities = extractor.extract_entities(sample_text)
    for e in entities:
        print(f"  [{e['entity_type']}] {e['name']} "
              f"(confidence={e['confidence']}, mentions={e['mention_count']})")

    print("\n=== Concept Extraction ===")
    concepts = extractor.extract_concepts(sample_text)
    for c in concepts:
        print(f"  [{c['domain']}] {c['name']} "
              f"(relevance={c['relevance_score']}, mentions={c['mention_count']})")

    print("\n=== Relationship Extraction ===")
    rels = extractor.extract_relationships(sample_text, entities)
    for r in rels:
        print(f"  {r['source']} --[{r['relation_type']}]--> {r['target']} "
              f"(strength={r['strength']})")
