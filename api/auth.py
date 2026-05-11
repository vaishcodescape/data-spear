"""API-key authentication for OmniGraph REST API.

Set OMNIGRAPH_API_KEY in your environment / .env file.
Leave it empty to run without authentication (development only).
Pass the key in the ``X-API-Key`` request header.
"""
import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str = Security(_api_key_header)) -> None:
    """FastAPI dependency — raises 401 if the key is wrong."""
    expected = os.getenv("OMNIGRAPH_API_KEY", "")
    if not expected:
        # No key configured → open access (dev mode)
        return
    if api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Supply it in the X-API-Key header.",
        )
