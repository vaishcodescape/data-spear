from __future__ import annotations

import logging
from typing import List, Optional

from .config import settings

logger = logging.getLogger("omnigraph.embedder")

MODEL_NAME = "voyage-3"
EMBEDDING_DIM = 1024

_client = None
_unavailable: Optional[Exception] = None


def _get_client():
    global _client, _unavailable
    if _unavailable is not None:
        raise _unavailable
    if _client is None:
        try:
            import voyageai
        except ImportError as exc:
            _unavailable = ImportError(
                "voyageai is required for semantic search. "
                "Install it with: pip install voyageai"
            )
            raise _unavailable from exc
        api_key = settings.voyage_api_key
        if not api_key:
            _unavailable = EnvironmentError(
                "VOYAGE_API_KEY environment variable is not set. "
                "Get your key at https://www.voyageai.com/"
            )
            raise _unavailable
        _client = voyageai.Client(api_key=api_key)
    return _client


def is_available() -> bool:
    try:
        _get_client()
        return True
    except (ImportError, EnvironmentError):
        return False


def generate_embedding(text: str, input_type: str = "document") -> List[float]:
    client = _get_client()
    result = client.embed([text.strip()[:32000]], model=MODEL_NAME, input_type=input_type)
    return [round(float(v), 6) for v in result.embeddings[0]]
