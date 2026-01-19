"""
BioGraph MVP v8.3 - API Dependencies

Shared dependencies for FastAPI application:
- Database connection pooling
- API key authentication
- Request ID generation
- Logging configuration

Per Sections 27-30 of spec.
"""

import os
import uuid
from typing import Optional, Iterator
from contextlib import contextmanager

from fastapi import Header, HTTPException, Request
from psycopg import Connection
from psycopg_pool import ConnectionPool
import structlog

logger = structlog.get_logger()

# Global connection pool (initialized at startup)
_pool: Optional[ConnectionPool] = None


def init_connection_pool(
    database_url: str,
    min_size: int = 5,
    max_size: int = 20,
    timeout: float = 10.0
) -> ConnectionPool:
    """
    Initialize database connection pool.

    Per Section 29: Connection pooling is REQUIRED.
    Pool is created ONCE at application startup.

    Args:
        database_url: Postgres connection URL
        min_size: Minimum pool connections
        max_size: Maximum pool connections
        timeout: Connection timeout in seconds

    Returns:
        ConnectionPool instance
    """
    global _pool

    logger.info(
        "database.pool.init",
        min_size=min_size,
        max_size=max_size,
        timeout=timeout
    )

    _pool = ConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        open=True
    )

    return _pool


def close_connection_pool():
    """Close database connection pool."""
    global _pool

    if _pool:
        logger.info("database.pool.close")
        _pool.close()
        _pool = None


@contextmanager
def get_db() -> Iterator[Connection]:
    """
    Get database connection from pool.

    Per Section 29: Connections are reused from pool (not created per-request).

    Yields:
        Database connection from pool

    Raises:
        HTTPException: If pool not initialized or connection fails
    """
    if not _pool:
        logger.error("database.pool.not_initialized")
        raise HTTPException(
            status_code=503,
            detail="Database connection pool not initialized"
        )

    try:
        with _pool.connection() as conn:
            yield conn
    except Exception as e:
        logger.error("database.connection.failed", exc_info=e)
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable"
        )


# API Key validation
def get_valid_api_keys() -> set:
    """
    Get valid API keys from environment.

    Per Section 28: API keys stored in environment variable.

    Returns:
        Set of valid API keys
    """
    api_keys_str = os.getenv("VALID_API_KEYS", "")
    if not api_keys_str:
        logger.warning("auth.no_api_keys_configured")
        return set()

    return set(key.strip() for key in api_keys_str.split(",") if key.strip())


VALID_API_KEYS = get_valid_api_keys()
AUTH_MODE = os.getenv("AUTH_MODE", "api_key")  # api_key, demo, disabled


async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> str:
    """
    Verify API key from X-API-Key header.

    Per Section 28: API key authentication required for admin/curation endpoints.

    Args:
        request: FastAPI request
        x_api_key: API key from header

    Returns:
        API key if valid

    Raises:
        HTTPException: 401 if missing or invalid
    """
    request_id = request.state.request_id

    # Check auth mode
    if AUTH_MODE == "disabled":
        logger.warning("auth.disabled", request_id=request_id)
        return "disabled"

    # Require API key
    if not x_api_key:
        logger.warning("auth.missing_api_key", request_id=request_id)
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header."
        )

    # Validate API key
    if x_api_key not in VALID_API_KEYS:
        logger.warning(
            "auth.invalid_api_key",
            request_id=request_id,
            api_key_prefix=x_api_key[:8] + "..."
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    logger.debug("auth.valid_api_key", request_id=request_id)
    return x_api_key


async def verify_api_key_optional(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> Optional[str]:
    """
    Verify API key (optional, for demo mode).

    Per Section 28: Read endpoints MAY be public in demo mode.

    Args:
        request: FastAPI request
        x_api_key: API key from header

    Returns:
        API key if provided and valid, None otherwise
    """
    if AUTH_MODE == "disabled":
        return None

    if AUTH_MODE == "demo" and not x_api_key:
        return None

    if x_api_key and x_api_key in VALID_API_KEYS:
        return x_api_key

    return None


def generate_request_id() -> str:
    """
    Generate unique request ID for tracing.

    Returns:
        Request ID (UUID4)
    """
    return f"req_{uuid.uuid4().hex[:12]}"
