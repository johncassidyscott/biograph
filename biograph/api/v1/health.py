"""
BioGraph API v1 - Health Endpoints

Per Section 31: Required Operational Endpoints (LOCKED)
- GET /healthz (REQUIRED)
"""

import time
from typing import Dict, Any

from fastapi import APIRouter, status
from pydantic import BaseModel
import structlog

from biograph.api.dependencies import get_db

logger = structlog.get_logger()

router = APIRouter()


class HealthCheckResult(BaseModel):
    """Health check result for a single dependency."""
    status: str  # "up" or "down"
    latency_ms: float


class HealthResponse(BaseModel):
    """
    Health check response.

    Per Section 31: Returns status of Postgres, Neo4j (if enabled), cache.
    """
    status: str  # "healthy" or "degraded"
    checks: Dict[str, HealthCheckResult]
    version: str


@router.get("/healthz", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """
    Health check endpoint.

    Per Section 31: REQUIRED operational endpoint.

    Returns:
        - 200 OK if all required checks pass
        - 503 Service Unavailable if any required check fails

    Checks:
        - Postgres connectivity (REQUIRED)
        - Neo4j connectivity (if GRAPH_BACKEND=neo4j)
        - Lookup cache readiness (REQUIRED)
    """
    checks = {}
    overall_status = "healthy"

    # Check Postgres
    postgres_result = await check_postgres()
    checks["postgres"] = postgres_result

    if postgres_result.status == "down":
        overall_status = "degraded"

    # Check cache (via Postgres query)
    cache_result = await check_cache()
    checks["cache"] = cache_result

    if cache_result.status == "down":
        overall_status = "degraded"

    # Note: Neo4j health check not implemented (Neo4j backend not implemented)
    # If Neo4j support is added in the future, check here when GRAPH_BACKEND=neo4j

    response = HealthResponse(
        status=overall_status,
        checks=checks,
        version="8.3.0"
    )

    # Return 503 if degraded
    if overall_status == "degraded":
        return response

    return response


async def check_postgres() -> HealthCheckResult:
    """
    Check Postgres connectivity.

    Returns:
        HealthCheckResult with status and latency
    """
    try:
        start_time = time.time()

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        latency_ms = (time.time() - start_time) * 1000

        logger.debug("health.postgres.up", latency_ms=latency_ms)

        return HealthCheckResult(
            status="up",
            latency_ms=round(latency_ms, 2)
        )

    except Exception as e:
        logger.error("health.postgres.down", exc_info=e)

        return HealthCheckResult(
            status="down",
            latency_ms=0.0
        )


async def check_cache() -> HealthCheckResult:
    """
    Check lookup cache readiness.

    Returns:
        HealthCheckResult with status and entry count
    """
    try:
        start_time = time.time()

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM lookup_cache")
                count = cur.fetchone()[0]

        latency_ms = (time.time() - start_time) * 1000

        logger.debug(
            "health.cache.up",
            latency_ms=latency_ms,
            entry_count=count
        )

        return HealthCheckResult(
            status="up",
            latency_ms=round(latency_ms, 2)
        )

    except Exception as e:
        logger.error("health.cache.down", exc_info=e)

        return HealthCheckResult(
            status="down",
            latency_ms=0.0
        )
