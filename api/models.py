"""Pydantic request / response schemas for the OmniGraph REST API."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str


class LoginResponse(BaseModel):
    user_id: int
    username: str
    full_name: str
    roles: List[str]


# ── Documents ─────────────────────────────────────────────────────────────────

SourceType = Literal[
    "report", "research_paper", "email", "technical_doc",
    "code_repository", "project_artifact", "presentation",
    "support_ticket", "log", "other",
]
SensitivityLevel = Literal["public", "internal", "confidential", "restricted"]


class IngestTextRequest(BaseModel):
    title: str
    content: str
    source_type: SourceType = "other"
    uploaded_by: int = Field(description="User ID of the uploader")
    sensitivity_level: SensitivityLevel = "internal"
    summary: Optional[str] = None
    auto_extract: bool = Field(
        default=True,
        description="Automatically extract entities/concepts/relations after ingest",
    )


class IngestUrlRequest(BaseModel):
    url: str
    title: Optional[str] = Field(
        default=None,
        description="Document title; auto-detected from page <title> if omitted",
    )
    source_type: SourceType = "other"
    uploaded_by: int
    sensitivity_level: SensitivityLevel = "internal"
    summary: Optional[str] = None
    auto_extract: bool = True


class IngestResponse(BaseModel):
    document_id: Optional[int]
    status: str
    extraction: Optional[Dict[str, Any]] = None


class DocumentSummary(BaseModel):
    document_id: int
    title: str
    source_type: str
    sensitivity_level: str
    is_archived: bool
    file_size_bytes: Optional[int]
    created_at: str


class DocumentDetail(DocumentSummary):
    content: str
    summary: Optional[str]
    content_hash: str


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    strategy: Literal["hybrid", "fulltext", "semantic", "graph"] = "hybrid"
    limit: int = Field(default=10, ge=1, le=100)
    user_id: int


class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]
    count: int
    strategy: str


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    user_id: int


class ChatResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]]
    tools_used: List[Dict[str, Any]]


# ── Graph ─────────────────────────────────────────────────────────────────────

class GraphStatsResponse(BaseModel):
    total_entities: int
    total_relations: int
    total_concepts: int
    total_documents: int
    total_taxonomy_nodes: int
    entities_by_type: Dict[str, int]
    relations_by_type: Dict[str, int]


class EntityItem(BaseModel):
    entity_id: int
    name: str
    entity_type: str
    confidence: float
    description: Optional[str]


class NeighborhoodResponse(BaseModel):
    entity_id: int
    neighbors: List[Dict[str, Any]]


class BuildGraphResponse(BaseModel):
    stats: Dict[str, Any]
    duplicates_detected: int
    documents_newly_extracted: int
