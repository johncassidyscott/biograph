#!/usr/bin/env python3
"""
BioGraph MVP API Endpoints

Implements investor-grade endpoints per spec section 9:
- Company dashboard
- "Why is this moving?" explanations
- Fixed explanation chains (Company → Drug → Target → Disease)

No free graph traversal - all queries use fixed templates.
"""
from flask import Blueprint, jsonify, request
from .db import get_conn

api = Blueprint('api_mvp', __name__)

@api.route('/api/companies', methods=['GET'])
def list_companies():
    """
    List all companies in universe.

    Query params:
    - universe_id: Filter by universe (optional)
    - ticker: Filter by ticker (optional)
    """
    universe_id = request.args.get('universe_id')
    ticker = request.args.get('ticker')

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
            companies = cur.fetchall()

            return jsonify({
                'count': len(companies),
                'companies': companies
            })

@api.route('/api/company/<cik>', methods=['GET'])
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
                return jsonify({'error': 'Company not found'}), 404

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

            pipeline = cur.fetchall()

            # Recent filings
            cur.execute("""
                SELECT accession_number, form_type, filing_date, edgar_url
                FROM filing
                WHERE company_cik = %s
                ORDER BY filing_date DESC
                LIMIT 10
            """, (cik,))

            filings = cur.fetchall()

            # Recent insider activity
            cur.execute("""
                SELECT insider_name, transaction_date, transaction_code,
                       shares, price_per_share
                FROM insider_transaction
                WHERE company_cik = %s
                ORDER BY transaction_date DESC
                LIMIT 10
            """, (cik,))

            insider_activity = cur.fetchall()

            return jsonify({
                'company': company,
                'pipeline': pipeline,
                'recent_filings': filings,
                'insider_activity': insider_activity
            })

@api.route('/api/explanation-chain/<cik>', methods=['GET'])
def get_explanation_chain(cik: str):
    """
    Get fixed explanation chains for a company.

    This is the core MVP query: Company → Drug → Target → Disease

    Query params:
    - disease_id: Filter by disease (optional)
    - target_id: Filter by target (optional)
    """
    disease_id = request.args.get('disease_id')
    target_id = request.args.get('target_id')

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
            chains = cur.fetchall()

            # Get evidence details
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

                chain['evidence'] = cur.fetchall()

            return jsonify({
                'company_cik': cik,
                'chains': chains,
                'count': len(chains)
            })

@api.route('/api/quality-metrics', methods=['GET'])
def get_quality_metrics():
    """
    Get quality metrics per spec section 10.1.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quality_metrics")
            metrics = cur.fetchone()

            # Calculate percentages
            if metrics['companies_in_universe'] > 0:
                metrics['pct_companies_with_drugs'] = round(
                    (metrics['companies_with_drugs'] / metrics['companies_in_universe']) * 100, 1
                )

            if metrics['total_drugs'] > 0:
                metrics['pct_drugs_with_targets'] = round(
                    (metrics['drugs_with_targets'] / metrics['total_drugs']) * 100, 1
                )
                metrics['pct_drugs_with_diseases'] = round(
                    (metrics['drugs_with_diseases'] / metrics['total_drugs']) * 100, 1
                )

            return jsonify(metrics)

@api.route('/api/search', methods=['GET'])
def search():
    """
    Simple search across companies, drugs, targets, diseases.

    Query params:
    - q: Search query
    - type: Filter by entity type (company, drug, target, disease)
    """
    query = request.args.get('q', '').strip()
    entity_type = request.args.get('type')

    if not query or len(query) < 2:
        return jsonify({'error': 'Query must be at least 2 characters'}), 400

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
                """, (f'%{query}%', f'%{query}%'))
                results['companies'] = cur.fetchall()

            # Search drugs
            if not entity_type or entity_type == 'drug':
                cur.execute("""
                    SELECT id, name, development_stage
                    FROM drug_program
                    WHERE name ILIKE %s
                    LIMIT 20
                """, (f'%{query}%',))
                results['drugs'] = cur.fetchall()

            # Search targets
            if not entity_type or entity_type == 'target':
                cur.execute("""
                    SELECT id, name, gene_symbol
                    FROM target
                    WHERE name ILIKE %s OR gene_symbol ILIKE %s
                    LIMIT 20
                """, (f'%{query}%', f'%{query}%'))
                results['targets'] = cur.fetchall()

            # Search diseases
            if not entity_type or entity_type == 'disease':
                cur.execute("""
                    SELECT id, name, therapeutic_area
                    FROM disease
                    WHERE name ILIKE %s
                    LIMIT 20
                """, (f'%{query}%',))
                results['diseases'] = cur.fetchall()

    return jsonify(results)

@api.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'version': '8.0-MVP',
        'description': 'BioGraph - Index-anchored intelligence graph for life sciences'
    })
