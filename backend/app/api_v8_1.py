#!/usr/bin/env python3
"""
BioGraph MVP API v8.1

Investor-grade endpoints with best-in-class fixes.

CRITICAL: Per Fix #2, UI queries read ONLY from explanation table.
- No free graph traversal
- Raw assertions are admin-only
- All product queries use fixed explanation chains
"""
from flask import Blueprint, jsonify, request
from datetime import date, datetime
from .db import get_conn

api = Blueprint('api_v8_1', __name__)

@api.route('/api/issuers', methods=['GET'])
def list_issuers():
    """
    List all issuers in universe.

    Query params:
    - universe_id: Filter by universe (optional)
    - ticker: Filter by ticker (optional)
    """
    universe_id = request.args.get('universe_id')
    ticker = request.args.get('ticker')

    with get_conn() as conn:
        with conn.cursor() as cur:
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
                query += " AND i.issuer_id IN (SELECT issuer_id FROM universe_membership WHERE universe_id = %s AND end_date IS NULL)"
                params.append(universe_id)

            if ticker:
                query += " AND c.ticker = %s"
                params.append(ticker.upper())

            query += " GROUP BY i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker, c.exchange, c.revenue_usd, c.employees ORDER BY c.ticker"

            cur.execute(query, params)
            issuers = cur.fetchall()

            return jsonify({
                'count': len(issuers),
                'issuers': issuers
            })

@api.route('/api/issuer/<issuer_id>', methods=['GET'])
def get_issuer(issuer_id: str):
    """
    Get issuer dashboard.

    Per Fix #2: Queries ONLY from explanation table (no raw assertions).

    Returns:
    - Issuer info
    - Pipeline (explanation chains)
    - Recent filings
    - Insider activity
    - HQ location
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Issuer info
            cur.execute("""
                SELECT i.*, c.sec_legal_name, c.ticker, c.exchange,
                       c.revenue_usd, c.employees
                FROM issuer i
                LEFT JOIN company c ON i.primary_cik = c.cik
                WHERE i.issuer_id = %s
            """, (issuer_id,))

            issuer = cur.fetchone()

            if not issuer:
                return jsonify({'error': 'Issuer not found'}), 404

            # HQ location (via assertion view)
            cur.execute("""
                SELECT il.location_id, l.name AS location_name, l.country_code
                FROM issuer_location il
                JOIN location l ON il.location_id = l.geonames_id
                WHERE il.issuer_id = %s
                  AND il.location_type = 'hq_operational'
                  AND il.retracted_at IS NULL
                LIMIT 1
            """, (issuer_id,))

            hq_location = cur.fetchone()

            # Pipeline (ONLY from explanation table - Fix #2)
            cur.execute("""
                SELECT
                    e.explanation_id,
                    e.drug_program_id,
                    dp.name AS drug_name,
                    dp.development_stage,
                    e.target_id,
                    t.name AS target_name,
                    t.gene_symbol,
                    e.disease_id,
                    d.name AS disease_name,
                    d.therapeutic_area,
                    e.strength_score,
                    e.as_of_date
                FROM explanation e
                JOIN drug_program dp ON e.drug_program_id = dp.drug_program_id
                JOIN target t ON e.target_id = t.target_id
                JOIN disease d ON e.disease_id = d.disease_id
                WHERE e.issuer_id = %s
                  AND e.as_of_date = CURRENT_DATE
                ORDER BY e.strength_score DESC
            """, (issuer_id,))

            pipeline = cur.fetchall()

            # Recent filings
            cur.execute("""
                SELECT accession_number, form_type, filing_date, edgar_url
                FROM filing
                WHERE company_cik = %s
                ORDER BY filing_date DESC
                LIMIT 10
            """, (issuer['primary_cik'],))

            filings = cur.fetchall()

            # Recent insider activity
            cur.execute("""
                SELECT insider_name, transaction_date, transaction_code,
                       shares, price_per_share
                FROM insider_transaction
                WHERE company_cik = %s
                ORDER BY transaction_date DESC
                LIMIT 10
            """, (issuer['primary_cik'],))

            insider_activity = cur.fetchall()

            return jsonify({
                'issuer': issuer,
                'hq_location': hq_location,
                'pipeline': pipeline,
                'recent_filings': filings,
                'insider_activity': insider_activity
            })

@api.route('/api/explanation/<issuer_id>', methods=['GET'])
def get_explanation_chains(issuer_id: str):
    """
    Get fixed explanation chains for an issuer.

    Per Fix #2: This is the ONLY query surface for UI.

    Query params:
    - disease_id: Filter by disease (optional)
    - target_id: Filter by target (optional)
    - as_of_date: Historical snapshot (default: today)
    """
    disease_id = request.args.get('disease_id')
    target_id = request.args.get('target_id')
    as_of_date = request.args.get('as_of_date', date.today().isoformat())

    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    e.explanation_id,
                    e.issuer_id,
                    i.primary_cik,
                    c.sec_legal_name AS company_name,
                    c.ticker,
                    e.drug_program_id,
                    dp.name AS drug_name,
                    dp.development_stage,
                    e.target_id,
                    t.name AS target_name,
                    t.gene_symbol,
                    e.disease_id,
                    d.name AS disease_name,
                    d.therapeutic_area,
                    e.strength_score,
                    e.as_of_date,
                    e.issuer_drug_assertion_id,
                    e.drug_target_assertion_id,
                    e.target_disease_assertion_id
                FROM explanation e
                JOIN issuer i ON e.issuer_id = i.issuer_id
                LEFT JOIN company c ON i.primary_cik = c.cik
                JOIN drug_program dp ON e.drug_program_id = dp.drug_program_id
                JOIN target t ON e.target_id = t.target_id
                JOIN disease d ON e.disease_id = d.disease_id
                WHERE e.issuer_id = %s
                  AND e.as_of_date = %s
            """
            params = [issuer_id, as_of_date]

            if disease_id:
                query += " AND e.disease_id = %s"
                params.append(disease_id)

            if target_id:
                query += " AND e.target_id = %s"
                params.append(target_id)

            query += " ORDER BY e.strength_score DESC"

            cur.execute(query, params)
            chains = cur.fetchall()

            # Get evidence for each chain
            for chain in chains:
                assertion_ids = [
                    chain['issuer_drug_assertion_id'],
                    chain['drug_target_assertion_id'],
                    chain['target_disease_assertion_id']
                ]

                cur.execute("""
                    SELECT
                        a.assertion_id,
                        a.predicate,
                        a.computed_confidence,
                        e.evidence_id,
                        e.source_system,
                        e.source_record_id,
                        e.license,
                        e.uri,
                        e.observed_at
                    FROM assertion a
                    JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
                    JOIN evidence e ON ae.evidence_id = e.evidence_id
                    WHERE a.assertion_id = ANY(%s)
                    ORDER BY a.assertion_id, e.observed_at DESC
                """, (assertion_ids,))

                chain['evidence'] = cur.fetchall()

            return jsonify({
                'issuer_id': issuer_id,
                'as_of_date': as_of_date,
                'chains': chains,
                'count': len(chains)
            })

@api.route('/api/explanation/<issuer_id>/changes', methods=['GET'])
def get_explanation_changes(issuer_id: str):
    """
    Get what changed since a prior date.

    Per Fix #8: As-of time semantics for "what changed since last quarter?"

    Query params:
    - since_date: Prior snapshot date (required)
    - as_of_date: Current snapshot date (default: today)
    """
    since_date = request.args.get('since_date')
    as_of_date = request.args.get('as_of_date', date.today().isoformat())

    if not since_date:
        return jsonify({'error': 'since_date is required'}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            # New explanations
            cur.execute("""
                SELECT e.*, dp.name AS drug_name, t.gene_symbol, d.name AS disease_name
                FROM explanation e
                JOIN drug_program dp ON e.drug_program_id = dp.drug_program_id
                JOIN target t ON e.target_id = t.target_id
                JOIN disease d ON e.disease_id = d.disease_id
                WHERE e.issuer_id = %s
                  AND e.as_of_date = %s
                  AND (e.drug_program_id, e.target_id, e.disease_id) NOT IN (
                      SELECT drug_program_id, target_id, disease_id
                      FROM explanation
                      WHERE issuer_id = %s AND as_of_date = %s
                  )
            """, (issuer_id, as_of_date, issuer_id, since_date))

            added = cur.fetchall()

            # Removed explanations
            cur.execute("""
                SELECT e.*, dp.name AS drug_name, t.gene_symbol, d.name AS disease_name
                FROM explanation e
                JOIN drug_program dp ON e.drug_program_id = dp.drug_program_id
                JOIN target t ON e.target_id = t.target_id
                JOIN disease d ON e.disease_id = d.disease_id
                WHERE e.issuer_id = %s
                  AND e.as_of_date = %s
                  AND (e.drug_program_id, e.target_id, e.disease_id) NOT IN (
                      SELECT drug_program_id, target_id, disease_id
                      FROM explanation
                      WHERE issuer_id = %s AND as_of_date = %s
                  )
            """, (issuer_id, since_date, issuer_id, as_of_date))

            removed = cur.fetchall()

            # Changed strength
            cur.execute("""
                SELECT
                    curr.*,
                    dp.name AS drug_name,
                    t.gene_symbol,
                    d.name AS disease_name,
                    prev.strength_score AS prev_strength_score,
                    (curr.strength_score - prev.strength_score) AS strength_delta
                FROM explanation curr
                JOIN explanation prev ON
                    curr.issuer_id = prev.issuer_id AND
                    curr.drug_program_id = prev.drug_program_id AND
                    curr.target_id = prev.target_id AND
                    curr.disease_id = prev.disease_id
                JOIN drug_program dp ON curr.drug_program_id = dp.drug_program_id
                JOIN target t ON curr.target_id = t.target_id
                JOIN disease d ON curr.disease_id = d.disease_id
                WHERE curr.issuer_id = %s
                  AND curr.as_of_date = %s
                  AND prev.as_of_date = %s
                  AND ABS(curr.strength_score - prev.strength_score) > 0.05
            """, (issuer_id, as_of_date, since_date))

            changed = cur.fetchall()

            return jsonify({
                'issuer_id': issuer_id,
                'since_date': since_date,
                'as_of_date': as_of_date,
                'added': added,
                'removed': removed,
                'changed': changed
            })

@api.route('/api/quality-metrics', methods=['GET'])
def get_quality_metrics():
    """
    Get quality metrics.

    Per spec Fix #6: Check licensing gates.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM quality_metrics")
            metrics = cur.fetchone()

            # Calculate percentages
            if metrics['issuers_in_universe'] > 0:
                metrics['pct_issuers_with_drugs'] = round(
                    (metrics['issuers_with_drugs'] / metrics['issuers_in_universe']) * 100, 1
                )

            if metrics['total_drugs'] > 0:
                metrics['pct_drugs_with_targets'] = round(
                    (metrics['drugs_with_targets'] / metrics['total_drugs']) * 100, 1
                )

            # Quality gates
            metrics['quality_gates'] = {
                'no_assertions_without_evidence': metrics['assertions_without_evidence'] == 0,
                'no_bad_licenses': metrics['evidence_with_bad_license'] == 0,
                'pct_issuers_with_drugs_gte_95': metrics.get('pct_issuers_with_drugs', 0) >= 95,
                'pct_drugs_with_targets_gte_90': metrics.get('pct_drugs_with_targets', 0) >= 90
            }

            return jsonify(metrics)

@api.route('/api/search', methods=['GET'])
def search():
    """
    Search across issuers, drugs, targets, diseases.

    Query params:
    - q: Search query
    - type: Filter by entity type
    """
    query = request.args.get('q', '').strip()
    entity_type = request.args.get('type')

    if not query or len(query) < 2:
        return jsonify({'error': 'Query must be at least 2 characters'}), 400

    results = {'issuers': [], 'drugs': [], 'targets': [], 'diseases': []}

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Search issuers
            if not entity_type or entity_type == 'issuer':
                cur.execute("""
                    SELECT i.issuer_id, i.primary_cik, c.sec_legal_name, c.ticker
                    FROM issuer i
                    LEFT JOIN company c ON i.primary_cik = c.cik
                    WHERE c.sec_legal_name ILIKE %s OR c.ticker ILIKE %s
                    LIMIT 20
                """, (f'%{query}%', f'%{query}%'))
                results['issuers'] = cur.fetchall()

            # Search drugs
            if not entity_type or entity_type == 'drug':
                cur.execute("""
                    SELECT drug_program_id, name, development_stage
                    FROM drug_program
                    WHERE name ILIKE %s
                    LIMIT 20
                """, (f'%{query}%',))
                results['drugs'] = cur.fetchall()

            # Search targets
            if not entity_type or entity_type == 'target':
                cur.execute("""
                    SELECT target_id, name, gene_symbol
                    FROM target
                    WHERE name ILIKE %s OR gene_symbol ILIKE %s
                    LIMIT 20
                """, (f'%{query}%', f'%{query}%'))
                results['targets'] = cur.fetchall()

            # Search diseases
            if not entity_type or entity_type == 'disease':
                cur.execute("""
                    SELECT disease_id, name, therapeutic_area
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
        'version': '8.1-MVP',
        'description': 'BioGraph - Investor-grade intelligence graph with best-in-class fixes'
    })

# Admin-only endpoints (not for UI)

@api.route('/api/admin/assertions', methods=['GET'])
def admin_list_assertions():
    """Admin-only: View raw assertions."""
    # This should be protected in production
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, COUNT(ae.evidence_id) AS evidence_count
                FROM assertion a
                LEFT JOIN assertion_evidence ae ON a.assertion_id = ae.assertion_id
                WHERE a.retracted_at IS NULL
                GROUP BY a.assertion_id
                ORDER BY a.created_at DESC
                LIMIT 100
            """)

            return jsonify({
                'assertions': cur.fetchall(),
                'warning': 'Admin-only endpoint. UI should NOT query raw assertions.'
            })
