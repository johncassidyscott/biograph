"""
BioGraph API v1 - Issuer Endpoints

Endpoints for querying issuers and explanation chains.

Per Section 27: All endpoints under /api/v1/*
Per Section 30: Error handling with structured responses
"""

from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Query, HTTPException, Request, status
from pydantic import BaseModel
import structlog

from biograph.api.dependencies import get_db, verify_api_key_optional

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1")


# Pydantic models
class Issuer(BaseModel):
    """Issuer summary."""
    issuer_id: str
    primary_cik: str
    sec_legal_name: Optional[str]
    ticker: Optional[str]
    exchange: Optional[str]
    revenue_usd: Optional[float]
    employees: Optional[int]
    drug_count: int


class IssuerListResponse(BaseModel):
    """Response for list_issuers endpoint."""
    count: int
    issuers: List[Issuer]
    page: int
    page_size: int


class ExplanationNode(BaseModel):
    """Node in explanation graph."""
    node_id: str
    node_type: str  # issuer, drug_program, target, disease
    label: str


class ExplanationEdge(BaseModel):
    """Edge in explanation graph."""
    edge_type: str  # HAS_PROGRAM, TARGETS, INDICATED_FOR
    source_id: str
    target_id: str
    confidence_band: str  # HIGH, MEDIUM, LOW
    confidence_score: Optional[float]
    evidence_count: int


class ExplanationResponse(BaseModel):
    """Response for get_explanation endpoint."""
    issuer_id: str
    as_of_date: date
    nodes: List[ExplanationNode]
    edges: List[ExplanationEdge]


# Endpoints
@router.get("/issuers", response_model=IssuerListResponse)
async def list_issuers(
    request: Request,
    universe_id: Optional[str] = Query(None, description="Filter by universe"),
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    api_key: Optional[str] = None  # Injected by dependency
):
    """
    List issuers in universe with pagination.

    Per Section 28: Read endpoints may be public in demo mode.

    Query Parameters:
        - universe_id: Filter by universe (optional)
        - ticker: Filter by ticker (optional)
        - page: Page number (default: 1)
        - page_size: Items per page (default: 20, max: 100)

    Returns:
        IssuerListResponse with paginated issuers
    """
    request_id = request.state.request_id

    try:
        logger.info(
            "issuers.list",
            request_id=request_id,
            universe_id=universe_id,
            ticker=ticker,
            page=page,
            page_size=page_size
        )

        offset = (page - 1) * page_size

        with get_db() as conn:
            with conn.cursor() as cur:
                # Build query
                query = """
                    SELECT i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker, c.exchange,
                           c.revenue_usd, c.employees,
                           COUNT(DISTINCT e.drug_program_id) as drug_count
                    FROM issuer i
                    LEFT JOIN company c ON i.primary_cik = c.cik
                    LEFT JOIN explanation e ON i.issuer_id = e.issuer_id
                        AND e.as_of_date = CURRENT_DATE
                    WHERE 1=1
                """
                params = []

                if universe_id:
                    query += """ AND i.issuer_id IN (
                        SELECT issuer_id FROM universe_membership
                        WHERE universe_id = %s AND end_date IS NULL
                    )"""
                    params.append(universe_id)

                if ticker:
                    query += " AND c.ticker = %s"
                    params.append(ticker.upper())

                query += """
                    GROUP BY i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker,
                             c.exchange, c.revenue_usd, c.employees
                    ORDER BY c.ticker NULLS LAST
                    LIMIT %s OFFSET %s
                """
                params.extend([page_size, offset])

                # Execute query
                cur.execute(query, params)
                rows = cur.fetchall()

                # Count total
                count_query = """
                    SELECT COUNT(DISTINCT i.issuer_id)
                    FROM issuer i
                    LEFT JOIN company c ON i.primary_cik = c.cik
                    WHERE 1=1
                """
                count_params = []

                if universe_id:
                    count_query += """ AND i.issuer_id IN (
                        SELECT issuer_id FROM universe_membership
                        WHERE universe_id = %s AND end_date IS NULL
                    )"""
                    count_params.append(universe_id)

                if ticker:
                    count_query += " AND c.ticker = %s"
                    count_params.append(ticker.upper())

                cur.execute(count_query, count_params)
                total_count = cur.fetchone()[0]

        # Convert to Pydantic models
        issuers = [
            Issuer(
                issuer_id=row[0],
                primary_cik=row[1],
                sec_legal_name=row[2],
                ticker=row[3],
                exchange=row[4],
                revenue_usd=row[5],
                employees=row[6],
                drug_count=row[7]
            )
            for row in rows
        ]

        logger.info(
            "issuers.list.success",
            request_id=request_id,
            count=len(issuers),
            total=total_count
        )

        return IssuerListResponse(
            count=total_count,
            issuers=issuers,
            page=page,
            page_size=page_size
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "issuers.list.error",
            exc_info=e,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list issuers"
        )


@router.get("/issuers/{issuer_id}", response_model=Issuer)
async def get_issuer(
    request: Request,
    issuer_id: str
):
    """
    Get issuer details.

    Path Parameters:
        - issuer_id: Issuer canonical ID

    Returns:
        Issuer details

    Raises:
        404: Issuer not found
    """
    request_id = request.state.request_id

    try:
        logger.info(
            "issuer.get",
            request_id=request_id,
            issuer_id=issuer_id
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker,
                           c.exchange, c.revenue_usd, c.employees,
                           COUNT(DISTINCT e.drug_program_id) as drug_count
                    FROM issuer i
                    LEFT JOIN company c ON i.primary_cik = c.cik
                    LEFT JOIN explanation e ON i.issuer_id = e.issuer_id
                        AND e.as_of_date = CURRENT_DATE
                    WHERE i.issuer_id = %s
                    GROUP BY i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker,
                             c.exchange, c.revenue_usd, c.employees
                """, (issuer_id,))

                row = cur.fetchone()

                if not row:
                    logger.warning(
                        "issuer.not_found",
                        request_id=request_id,
                        issuer_id=issuer_id
                    )
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Issuer {issuer_id} not found"
                    )

        issuer = Issuer(
            issuer_id=row[0],
            primary_cik=row[1],
            sec_legal_name=row[2],
            ticker=row[3],
            exchange=row[4],
            revenue_usd=row[5],
            employees=row[6],
            drug_count=row[7]
        )

        logger.info(
            "issuer.get.success",
            request_id=request_id,
            issuer_id=issuer_id
        )

        return issuer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "issuer.get.error",
            exc_info=e,
            request_id=request_id,
            issuer_id=issuer_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get issuer"
        )
