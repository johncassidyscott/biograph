"""
BioGraph API v1 - Admin Endpoints

Administrative endpoints requiring API key authentication.

Per Section 28: Admin endpoints MUST be API-key gated.
"""

from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException, status
from pydantic import BaseModel
import structlog

from biograph.api.dependencies import get_db, verify_api_key

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/admin")


# Pydantic models
class AssertionSummary(BaseModel):
    """Summary of an assertion for admin view."""
    assertion_id: int
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    computed_confidence: float
    evidence_count: int
    asserted_at: datetime
    created_at: datetime


class AssertionListResponse(BaseModel):
    """Response for list_assertions endpoint."""
    assertions: List[AssertionSummary]
    count: int
    warning: str


# Endpoints
@router.get("/assertions", response_model=AssertionListResponse)
async def list_assertions(
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """
    List raw assertions (admin-only).

    Per Section 28: Admin endpoints require API key authentication.
    Per Section 4: UI should NOT query raw assertions (explanation table only).

    This endpoint is for:
    - Administrative debugging
    - Data quality review
    - Audit purposes

    Authentication:
        Requires X-API-Key header

    Returns:
        AssertionListResponse with raw assertions

    Raises:
        401: Missing or invalid API key
    """
    request_id = request.state.request_id

    try:
        logger.info(
            "admin.assertions.list",
            request_id=request_id,
            api_key_prefix=api_key[:8] + "..."
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.assertion_id, a.subject_id, a.subject_type, a.predicate,
                           a.object_id, a.object_type, a.computed_confidence,
                           a.asserted_at, a.created_at,
                           COUNT(ae.evidence_id) AS evidence_count
                    FROM assertion a
                    LEFT JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
                    WHERE a.retracted_at IS NULL
                    GROUP BY a.assertion_id, a.subject_id, a.subject_type, a.predicate,
                             a.object_id, a.object_type, a.computed_confidence,
                             a.asserted_at, a.created_at
                    ORDER BY a.created_at DESC
                    LIMIT 100
                """)

                rows = cur.fetchall()

        assertions = [
            AssertionSummary(
                assertion_id=row[0],
                subject_id=row[1],
                subject_type=row[2],
                predicate=row[3],
                object_id=row[4],
                object_type=row[5],
                computed_confidence=row[6],
                asserted_at=row[7],
                created_at=row[8],
                evidence_count=row[9]
            )
            for row in rows
        ]

        logger.info(
            "admin.assertions.list.success",
            request_id=request_id,
            count=len(assertions)
        )

        return AssertionListResponse(
            assertions=assertions,
            count=len(assertions),
            warning="Admin-only endpoint. UI should NOT query raw assertions. Use explanation table instead."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "admin.assertions.list.error",
            exc_info=e,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list assertions"
        )
