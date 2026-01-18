#!/usr/bin/env python3
"""
Phase 2: SEC EDGAR Filings Ingestion

Loads filings metadata for universe companies:
- Filings metadata (10-K, 10-Q, 8-K, etc.)
- 8-K item codes
- Select XBRL concepts (≤30 per spec)
- Exhibit index (metadata only)

Per spec section 4: Data sources = SEC EDGAR (filings metadata, 8-K items, XBRL highlights)
"""
import json
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from urllib import request, error
from ..app.db import get_conn

USER_AGENT = "BioGraph/1.0 (biograph-support@example.com)"

# Select XBRL concepts (≤30 per spec)
# Focus on investor-relevant metrics
XBRL_CONCEPTS_TO_EXTRACT = [
    'Revenues',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'NetIncomeLoss',
    'EarningsPerShareBasic',
    'EarningsPerShareDiluted',
    'Assets',
    'Liabilities',
    'StockholdersEquity',
    'CashAndCashEquivalentsAtCarryingValue',
    'ResearchAndDevelopmentExpense',
    'SellingGeneralAndAdministrativeExpense',
    'OperatingIncomeLoss',
    'WeightedAverageNumberOfSharesOutstandingBasic',
    'WeightedAverageNumberOfDilutedSharesOutstanding',
    'LongTermDebt',
    'ShortTermDebt',
]

def fetch_company_filings(cik: str, form_types: Optional[List[str]] = None,
                         limit: int = 100) -> List[Dict]:
    """
    Fetch filings for a company from SEC EDGAR.

    Args:
        cik: 10-digit CIK
        form_types: Filter by form types (e.g., ['10-K', '10-Q', '8-K'])
        limit: Max filings to return

    Returns:
        List of filing dicts with metadata

    Uses SEC Submissions API: https://data.sec.gov/submissions/CIK{cik}.json
    """
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    req = request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with request.urlopen(req) as response:
            data = json.loads(response.read().decode())

            filings = []
            recent_filings = data.get('filings', {}).get('recent', {})

            if not recent_filings:
                return []

            # Process filings
            count = len(recent_filings.get('accessionNumber', []))

            for i in range(min(count, limit)):
                form_type = recent_filings['form'][i]

                # Filter by form type if specified
                if form_types and form_type not in form_types:
                    continue

                filing = {
                    'accession_number': recent_filings['accessionNumber'][i],
                    'form_type': form_type,
                    'filing_date': recent_filings['filingDate'][i],
                    'accepted_at': recent_filings.get('acceptanceDateTime', [None] * count)[i],
                    'primary_document': recent_filings.get('primaryDocument', [None] * count)[i],
                    'primary_doc_description': recent_filings.get('primaryDocDescription', [None] * count)[i],
                }

                # Build EDGAR URL
                accession_no_dashes = filing['accession_number'].replace('-', '')
                filing['edgar_url'] = (
                    f"https://www.sec.gov/cgi-bin/viewer?"
                    f"action=view&cik={cik_padded}&accession_number={filing['accession_number']}"
                )

                filings.append(filing)

            return filings

    except error.HTTPError as e:
        print(f"  ✗ HTTP error fetching filings for CIK {cik_padded}: {e}")
        return []

    except Exception as e:
        print(f"  ✗ Error fetching filings for CIK {cik_padded}: {e}")
        return []

def parse_8k_items(filing_url: str) -> Optional[List[str]]:
    """
    Parse 8-K item codes from filing.

    This is a simplified version - production would parse the XML filing.
    For MVP, we return None and can enhance later.

    Args:
        filing_url: URL to filing

    Returns:
        List of item codes (e.g., ['1.01', '9.01']) or None
    """
    # TODO: Implement 8-K XML parsing
    # For MVP, return None
    return None

def extract_xbrl_concepts(accession_number: str, cik: str) -> Optional[Dict]:
    """
    Extract select XBRL concepts from filing.

    This is simplified for MVP - would fetch from XBRL API in production.

    Args:
        accession_number: Filing accession number
        cik: Company CIK

    Returns:
        Dict of XBRL concepts or None
    """
    # TODO: Implement XBRL extraction using SEC XBRL API
    # For MVP, return None (can enhance later)
    return None

def load_filings_for_company(cik: str, form_types: Optional[List[str]] = None,
                             lookback_days: int = 365) -> Dict[str, int]:
    """
    Load filings for a single company.

    Args:
        cik: Company CIK
        form_types: Form types to load (None = all)
        lookback_days: Only load filings from last N days

    Returns:
        Stats dict
    """
    stats = {'inserted': 0, 'updated': 0, 'skipped': 0}

    print(f"Loading filings for CIK {cik}...")

    filings = fetch_company_filings(cik, form_types)

    if not filings:
        print(f"  ⚠ No filings found")
        return stats

    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).date()

    with get_conn() as conn:
        with conn.cursor() as cur:
            for filing in filings:
                filing_date = datetime.strptime(filing['filing_date'], '%Y-%m-%d').date()

                # Skip old filings
                if filing_date < cutoff_date:
                    stats['skipped'] += 1
                    continue

                # Parse 8-K items if applicable
                items_8k = None
                if filing['form_type'] == '8-K':
                    items_8k = parse_8k_items(filing['edgar_url'])

                # Extract XBRL (for 10-K, 10-Q)
                xbrl_summary = None
                if filing['form_type'] in ['10-K', '10-Q']:
                    xbrl_summary = extract_xbrl_concepts(
                        filing['accession_number'], cik
                    )

                # Insert filing
                try:
                    cur.execute("""
                        INSERT INTO filing
                        (accession_number, company_cik, form_type, filing_date,
                         accepted_at, items_8k, xbrl_summary, edgar_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (accession_number) DO UPDATE
                        SET form_type = EXCLUDED.form_type,
                            filing_date = EXCLUDED.filing_date,
                            items_8k = EXCLUDED.items_8k,
                            xbrl_summary = EXCLUDED.xbrl_summary
                        RETURNING accession_number
                    """, (
                        filing['accession_number'],
                        cik,
                        filing['form_type'],
                        filing_date,
                        filing.get('accepted_at'),
                        items_8k,
                        json.dumps(xbrl_summary) if xbrl_summary else None,
                        filing['edgar_url']
                    ))

                    if cur.fetchone():
                        stats['inserted'] += 1
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    print(f"    ✗ Error inserting filing {filing['accession_number']}: {e}")
                    conn.rollback()
                    continue

            conn.commit()

    print(f"  ✓ Inserted: {stats['inserted']}, Updated: {stats['updated']}, Skipped: {stats['skipped']}")
    return stats

def batch_load_filings(ciks: Optional[List[str]] = None,
                      form_types: Optional[List[str]] = None,
                      lookback_days: int = 365,
                      rate_limit_delay: float = 0.15) -> Dict[str, int]:
    """
    Load filings for all companies in universe.

    Args:
        ciks: List of CIKs (None = all companies in DB)
        form_types: Form types to load (e.g., ['10-K', '10-Q', '8-K'])
        lookback_days: Only load filings from last N days
        rate_limit_delay: Delay between requests (SEC limit: 10 req/sec)

    Returns:
        Aggregate stats
    """
    if not ciks:
        # Get all companies from database
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT cik FROM company ORDER BY cik")
                ciks = [row['cik'] for row in cur.fetchall()]

    total_stats = {'inserted': 0, 'updated': 0, 'skipped': 0, 'companies_processed': 0}

    # Log start
    log_id = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_log
                (phase, source_system, records_processed, started_at, status, metadata)
                VALUES ('corporate_spine', 'sec_edgar', %s, NOW(), 'running', %s)
                RETURNING id
            """, (len(ciks), json.dumps({'form_types': form_types, 'lookback_days': lookback_days})))
            log_id = cur.fetchone()['id']
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Phase 2: SEC EDGAR Filings Ingestion")
    print(f"{'='*60}")
    print(f"Companies: {len(ciks)}")
    print(f"Form types: {form_types or 'all'}")
    print(f"Lookback: {lookback_days} days")

    for i, cik in enumerate(ciks, 1):
        print(f"\n[{i}/{len(ciks)}]", end=" ")

        try:
            stats = load_filings_for_company(cik, form_types, lookback_days)
            total_stats['inserted'] += stats['inserted']
            total_stats['updated'] += stats['updated']
            total_stats['skipped'] += stats['skipped']
            total_stats['companies_processed'] += 1

            # Rate limiting
            time.sleep(rate_limit_delay)

        except Exception as e:
            print(f"  ✗ Error: {e}")

    # Update log
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingestion_log
                SET records_inserted = %s,
                    records_updated = %s,
                    records_discarded = %s,
                    completed_at = NOW(),
                    status = 'completed'
                WHERE id = %s
            """, (total_stats['inserted'], total_stats['updated'],
                 total_stats['skipped'], log_id))
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Filings Ingestion Complete")
    print(f"{'='*60}")
    print(f"Companies processed: {total_stats['companies_processed']}")
    print(f"Filings inserted: {total_stats['inserted']}")
    print(f"Filings updated: {total_stats['updated']}")
    print(f"Filings skipped: {total_stats['skipped']}")

    return total_stats

if __name__ == "__main__":
    import sys

    # Default to major forms for MVP
    default_forms = ['10-K', '10-Q', '8-K']

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all-forms':
            forms = None
        else:
            forms = sys.argv[1].split(',')
    else:
        forms = default_forms

    batch_load_filings(form_types=forms)
