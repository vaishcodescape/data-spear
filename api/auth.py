"""API-key authentication for OmniGraph REST API.

Set OMNIGRAPH_API_KEY in your environment / .env file.
Leave it empty to run without authentication (development only).
Pass the key in the ``X-API-Key`` request header.
"""
import logging

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from omnigraph.config import settings

logger = logging.getLogger("omnigraph.api.auth")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str = Security(_api_key_header)) -> None:
    """FastAPI dependency — raises 401 if the key is wrong or missing."""
    expected = settings.api_key
    if not expected:
        logger.warning(
            "OMNIGRAPH_API_KEY is not set — running without authentication. "
            "This is unsafe in production."
        )
        return
    if api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Supply it in the X-API-Key header.",
        )
