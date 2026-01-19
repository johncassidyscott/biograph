#!/usr/bin/env python3
"""
Phase 1: CIK Resolution and Validation

Per spec section 8 (Ingestion order):
- Resolve and validate one CIK per issuer
- Store SEC legal name
- Gate: No CIK = no company

This module queries SEC EDGAR to validate CIKs and fetch official company names.
"""
import time
import json
from typing import Optional, Dict
from urllib import request, error
from datetime import datetime
from ..app.db import get_conn

# SEC EDGAR requires a User-Agent header
# Per SEC policy: https://www.sec.gov/os/accessing-edgar-data
USER_AGENT = "BioGraph/1.0 (biograph-support@example.com)"

def fetch_company_info_from_sec(cik: str) -> Optional[Dict]:
    """
    Fetch company information from SEC EDGAR.

    Args:
        cik: 10-digit CIK string (zero-padded)

    Returns:
        Dict with 'cik', 'name', 'tickers', 'exchanges' or None if not found

    SEC API endpoint:
    https://data.sec.gov/submissions/CIK{cik}.json
    """
    cik_padded = cik.zfill(10)

    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    req = request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with request.urlopen(req) as response:
            data = json.loads(response.read().decode())

            # Extract core fields
            return {
                'cik': cik_padded,
                'name': data.get('name', ''),
                'tickers': data.get('tickers', []),
                'exchanges': data.get('exchanges', []),
                'sic': data.get('sic'),
                'sic_description': data.get('sicDescription'),
                'fiscal_year_end': data.get('fiscalYearEnd'),
                'state_of_incorporation': data.get('stateOfIncorporation'),
                'addresses': {
                    'mailing': data.get('addresses', {}).get('mailing'),
                    'business': data.get('addresses', {}).get('business')
                }
            }

    except error.HTTPError as e:
        if e.code == 404:
            print(f"  ✗ CIK {cik_padded} not found in SEC EDGAR")
            return None
        else:
            print(f"  ✗ HTTP error fetching CIK {cik_padded}: {e}")
            raise

    except Exception as e:
        print(f"  ✗ Error fetching CIK {cik_padded}: {e}")
        raise

def resolve_and_store_cik(cik: str, log_ingestion: bool = True) -> bool:
    """
    Resolve a CIK from SEC EDGAR and store in company table.

    Args:
        cik: CIK to resolve (will be normalized)
        log_ingestion: Whether to log to ingestion_log table

    Returns:
        True if successful, False if CIK invalid or not found

    Per spec: No CIK = no company (hard gate)
    """
    cik_normalized = cik.zfill(10)

    print(f"Resolving CIK {cik_normalized} from SEC EDGAR...")

    # Fetch from SEC
    info = fetch_company_info_from_sec(cik_normalized)
    if not info:
        return False

    # Extract primary ticker and exchange
    ticker = info['tickers'][0] if info['tickers'] else None
    exchange = info['exchanges'][0] if info['exchanges'] else None

    # Store in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO company (cik, sec_legal_name, ticker, exchange)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (cik) DO UPDATE
                SET sec_legal_name = EXCLUDED.sec_legal_name,
                    ticker = EXCLUDED.ticker,
                    exchange = EXCLUDED.exchange,
                    updated_at = NOW()
                RETURNING cik
            """, (cik_normalized, info['name'], ticker, exchange))

            result = cur.fetchone()
            conn.commit()

            if result:
                print(f"  ✓ {info['name']} ({ticker or 'N/A'}) → CIK {cik_normalized}")
                return True

    return False

def batch_resolve_ciks(ciks: list[str], rate_limit_delay: float = 0.1) -> Dict[str, int]:
    """
    Resolve multiple CIKs from universe in batch.

    Args:
        ciks: List of CIK strings
        rate_limit_delay: Delay between SEC requests (respect rate limits)

    Returns:
        Stats dict with 'resolved', 'failed' counts

    Per SEC policy: Max 10 requests/second
    """
    stats = {'resolved': 0, 'failed': 0}

    log_id = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_log
                (phase, source_system, records_processed, started_at, status)
                VALUES ('cik_lock', 'sec_edgar', %s, NOW(), 'running')
                RETURNING id
            """, (len(ciks),))
            log_id = cur.fetchone()['id']
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Phase 1: CIK Resolution")
    print(f"{'='*60}")
    print(f"Resolving {len(ciks)} CIKs from SEC EDGAR...")

    for i, cik in enumerate(ciks, 1):
        print(f"\n[{i}/{len(ciks)}]", end=" ")

        try:
            if resolve_and_store_cik(cik):
                stats['resolved'] += 1
            else:
                stats['failed'] += 1

            # Rate limiting
            time.sleep(rate_limit_delay)

        except Exception as e:
            print(f"  ✗ Error: {e}")
            stats['failed'] += 1

    # Update log
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ingestion_log
                SET records_inserted = %s,
                    records_discarded = %s,
                    completed_at = NOW(),
                    status = 'completed'
                WHERE id = %s
            """, (stats['resolved'], stats['failed'], log_id))
            conn.commit()

    print(f"\n{'='*60}")
    print(f"CIK Resolution Complete")
    print(f"{'='*60}")
    print(f"Resolved: {stats['resolved']}")
    print(f"Failed: {stats['failed']}")

    return stats

if __name__ == "__main__":
    import sys
    from .load_universe import get_universe_companies

    if len(sys.argv) < 2:
        print("Usage: python resolve_cik.py <universe_id|all>")
        sys.exit(1)

    universe_id = sys.argv[1] if sys.argv[1] != 'all' else None

    # Get CIKs from universe
    ciks = get_universe_companies(universe_id)
    print(f"Found {len(ciks)} companies in universe")

    # Resolve all
    batch_resolve_ciks(ciks)
