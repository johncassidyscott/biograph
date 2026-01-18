#!/usr/bin/env python3
"""
BioGraph MVP FastAPI Application

Investor-grade intelligence graph API matching spec v8.0.
"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.app.db import get_conn

app = FastAPI(
    title="BioGraph MVP",
    version="8.0-MVP",
    description="Index-anchored intelligence graph for life sciences"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Frontend Routes
# ============================================================================

@app.get("/")
def root():
    return FileResponse("frontend/index_mvp.html")

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/health")
def health():
    """Health check endpoint."""
    return {
        'status': 'ok',
        'version': '8.0-MVP',
        'description': 'BioGraph - Index-anchored intelligence graph for life sciences'
    }

@app.get("/api/companies")
def list_companies(universe_id: str = Query(None), ticker: str = Query(None)):
    """
    List all companies in universe.

    Args:
        universe_id: Filter by universe (optional)
        ticker: Filter by ticker (optional)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT c.cik, c.sec_legal_name, c.ticker, c.exchange,
                       c.revenue_usd, c.employees,
                       COUNT(DISTINCT cd.drug_id) as drug_count
                FROM company c
                LEFT JOIN company_drug cd ON c.cik = cd.company_cik AND cd.valid_to IS NULL
                WHERE 1=1
            """
            params = []

            if universe_id:
                query += " AND c.cik IN (SELECT company_cik FROM universe_membership WHERE universe_id = %s AND end_date IS NULL)"
                params.append(universe_id)

            if ticker:
                query += " AND c.ticker = %s"
                params.append(ticker.upper())

            query += " GROUP BY c.cik ORDER BY c.ticker"

            cur.execute(query, params)
            companies = [dict(row) for row in cur.fetchall()]

            return {
                'count': len(companies),
                'companies': companies
            }

@app.get("/api/company/{cik}")
def get_company(cik: str):
    """
    Get company dashboard per spec section 9.1:
    - Pipeline summary (program → target → disease)
    - Evidence strength indicators
    - Recent filings + insider signals
    - Location + peer density
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Company info
            cur.execute("""
                SELECT c.*, l.name as hq_location
                FROM company c
                LEFT JOIN company_location cl ON c.cik = cl.company_cik
                    AND cl.location_type = 'hq_operational' AND cl.valid_to IS NULL
                LEFT JOIN location l ON cl.location_id = l.geonames_id
                WHERE c.cik = %s
            """, (cik,))

            company = cur.fetchone()

            if not company:
                raise HTTPException(status_code=404, detail='Company not found')

            company = dict(company)

            # Pipeline (explanation chains)
            cur.execute("""
                SELECT drug_id, drug_name, development_stage,
                       target_id, target_name, gene_symbol,
                       disease_id, disease_name, therapeutic_area,
                       association_score
                FROM explanation_chain
                WHERE cik = %s
                ORDER BY association_score DESC
            """, (cik,))

            pipeline = [dict(row) for row in cur.fetchall()]

            # Recent filings
            cur.execute("""
                SELECT accession_number, form_type, filing_date, edgar_url
                FROM filing
                WHERE company_cik = %s
                ORDER BY filing_date DESC
                LIMIT 10
            """, (cik,))

            filings = [dict(row) for row in cur.fetchall()]

            # Recent insider activity
            cur.execute("""
                SELECT insider_name, transaction_date, transaction_code,
                       shares, price_per_share
                FROM insider_transaction
                WHERE company_cik = %s
                ORDER BY transaction_date DESC
                LIMIT 10
            """, (cik,))

            insider_activity = [dict(row) for row in cur.fetchall()]

            return {
                'company': company,
                'pipeline': pipeline,
                'recent_filings': filings,
                'insider_activity': insider_activity
            }

@app.get("/api/explanation-chain/{cik}")
def get_explanation_chain(cik: str, disease_id: str = Query(None), target_id: str = Query(None)):
    """
    Get fixed explanation chains for a company.

    This is the core MVP query: Company → Drug → Target → Disease

    Args:
        cik: Company CIK
        disease_id: Filter by disease (optional)
        target_id: Filter by target (optional)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    cik, company_name, ticker,
                    drug_id, drug_name, development_stage,
                    target_id, target_name, gene_symbol,
                    disease_id, disease_name, therapeutic_area,
                    association_score,
                    company_drug_evidence_id,
                    drug_target_evidence_id,
                    target_disease_evidence_id
                FROM explanation_chain
                WHERE cik = %s
            """
            params = [cik]

            if disease_id:
                query += " AND disease_id = %s"
                params.append(disease_id)

            if target_id:
                query += " AND target_id = %s"
                params.append(target_id)

            query += " ORDER BY association_score DESC"

            cur.execute(query, params)
            chains = [dict(row) for row in cur.fetchall()]

            # Get evidence details for each chain
            for chain in chains:
                evidence_ids = [
                    chain['company_drug_evidence_id'],
                    chain['drug_target_evidence_id'],
                    chain['target_disease_evidence_id']
                ]

                cur.execute("""
                    SELECT id, source_system, source_record_id, evidence_type,
                           confidence, license, url, observed_at
                    FROM evidence
                    WHERE id = ANY(%s)
                """, (evidence_ids,))

                chain['evidence'] = [dict(row) for row in cur.fetchall()]

            return {
                'company_cik': cik,
                'chains': chains,
                'count': len(chains)
            }

@app.get("/api/quality-metrics")
def get_quality_metrics():
    """
    Get quality metrics per spec section 10.1.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quality_metrics")
            metrics = dict(cur.fetchone() or {})

            # Calculate percentages
            if metrics.get('companies_in_universe', 0) > 0:
                metrics['pct_companies_with_drugs'] = round(
                    (metrics['companies_with_drugs'] / metrics['companies_in_universe']) * 100, 1
                )

            if metrics.get('total_drugs', 0) > 0:
                metrics['pct_drugs_with_targets'] = round(
                    (metrics['drugs_with_targets'] / metrics['total_drugs']) * 100, 1
                )
                metrics['pct_drugs_with_diseases'] = round(
                    (metrics['drugs_with_diseases'] / metrics['total_drugs']) * 100, 1
                )

            return metrics

@app.get("/api/search")
def search(q: str = Query(..., min_length=2), entity_type: str = Query(None)):
    """
    Simple search across companies, drugs, targets, diseases.

    Args:
        q: Search query (min 2 chars)
        entity_type: Filter by entity type (company, drug, target, disease)
    """
    results = {'companies': [], 'drugs': [], 'targets': [], 'diseases': []}

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Search companies
            if not entity_type or entity_type == 'company':
                cur.execute("""
                    SELECT cik, sec_legal_name, ticker
                    FROM company
                    WHERE sec_legal_name ILIKE %s OR ticker ILIKE %s
                    LIMIT 20
                """, (f'%{q}%', f'%{q}%'))
                results['companies'] = [dict(row) for row in cur.fetchall()]

            # Search drugs
            if not entity_type or entity_type == 'drug':
                cur.execute("""
                    SELECT id, name, development_stage
                    FROM drug_program
                    WHERE name ILIKE %s
                    LIMIT 20
                """, (f'%{q}%',))
                results['drugs'] = [dict(row) for row in cur.fetchall()]

            # Search targets
            if not entity_type or entity_type == 'target':
                cur.execute("""
                    SELECT id, name, gene_symbol
                    FROM target
                    WHERE name ILIKE %s OR gene_symbol ILIKE %s
                    LIMIT 20
                """, (f'%{q}%', f'%{q}%'))
                results['targets'] = [dict(row) for row in cur.fetchall()]

            # Search diseases
            if not entity_type or entity_type == 'disease':
                cur.execute("""
                    SELECT id, name, therapeutic_area
                    FROM disease
                    WHERE name ILIKE %s
                    LIMIT 20
                """, (f'%{q}%',))
                results['diseases'] = [dict(row) for row in cur.fetchall()]

    return results

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)
