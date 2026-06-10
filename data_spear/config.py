from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RowSource(BaseModel):
    # Ingest each row of `table` as a single chunk, serialized as 'col: value' lines.
    mode: Literal["row"] = "row"
    table: str
    id_column: str = "id"
    columns: list[str] | None = None  # None = all columns
    where: str | None = None


class DocumentSource(BaseModel):
    # Ingest one or more text columns per row, chunked into windows.
    mode: Literal["document"] = "document"
    table: str
    id_column: str = "id"
    text_columns: list[str]
    where: str | None = None
    chunk_size: int = 800   # characters per chunk
    chunk_overlap: int = 120


Source = RowSource | DocumentSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index: str = "data-spear"
    pinecone_namespace: str = "default"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    # Integrated-inference embedding model hosted by Pinecone.
    embedding_model: str = "llama-text-embed-v2"

    # Anthropic
    anthropic_api_key: str = ""
    answer_model: str = "claude-opus-4-8"

    # Retrieval
    top_k: int = 6

    # API service
    # Optional bearer token; when set, all endpoints except /healthz require
    # `Authorization: Bearer <token>`.
    api_token: str = ""

    # Agent safety
    # Per-statement timeout for SQL the agent runs, in milliseconds.
    statement_timeout_ms: int = 30000


# Define what to ingest here. Edit for your schema.
SOURCES: list[Source] = [
    # Example: structured rows
    # RowSource(table="customers", id_column="id"),
    #
    # Example: documents
    # DocumentSource(table="articles", text_columns=["title", "body"]),
]


settings = Settings()
