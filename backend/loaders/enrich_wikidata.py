#!/usr/bin/env python3
"""
Phase 3: Wikidata Enrichment

Enriches company data with:
- Wikidata QID (for joins)
- Headquarters location (GeoNames)
- Revenue
- Employee count
- Ticker/exchange validation

Per spec section 7.1: Priority order = Wikidata HQ → GeoNames

Data source: Wikidata Query Service (CC0 license)
"""
import json
import time
from typing import Optional, Dict, List
from urllib import request, parse, error
from datetime import datetime
from ..app.db import get_conn

WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "BioGraph/1.0 (biograph-support@example.com)"

def query_wikidata(sparql: str) -> List[Dict]:
    """
    Execute SPARQL query against Wikidata.

    Args:
        sparql: SPARQL query string

    Returns:
        List of result bindings
    """
    params = {
        'query': sparql,
        'format': 'json'
    }

    url = f"{WIKIDATA_SPARQL_ENDPOINT}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get('results', {}).get('bindings', [])

    except Exception as e:
        print(f"  ✗ Wikidata query error: {e}")
        return []

def find_wikidata_by_cik(cik: str) -> Optional[str]:
    """
    Find Wikidata QID for a company by SEC CIK.

    Args:
        cik: SEC CIK (10-digit, zero-padded)

    Returns:
        Wikidata QID (e.g., 'Q312') or None
    """
    # Remove leading zeros for Wikidata query
    cik_int = str(int(cik))

    sparql = f"""
    SELECT ?item WHERE {{
      ?item wdt:P5531 "{cik_int}".
    }}
    """

    results = query_wikidata(sparql)

    if results:
        qid = results[0]['item']['value'].split('/')[-1]
        return qid

    return None

def get_wikidata_company_data(qid: str) -> Optional[Dict]:
    """
    Fetch company data from Wikidata.

    Args:
        qid: Wikidata QID

    Returns:
        Dict with company data or None
    """
    sparql = f"""
    SELECT ?ticker ?exchange ?exchangeLabel ?revenue ?employees
           ?hqGeoNames ?hqLabel ?countryLabel
    WHERE {{
      OPTIONAL {{ wd:{qid} wdt:P414 ?exchange. }}
      OPTIONAL {{ wd:{qid} wdt:P249 ?ticker. }}
      OPTIONAL {{ wd:{qid} wdt:P2139 ?revenue. }}
      OPTIONAL {{ wd:{qid} wdt:P1128 ?employees. }}
      OPTIONAL {{
        wd:{qid} wdt:P159 ?hq.
        OPTIONAL {{ ?hq wdt:P1566 ?hqGeoNames. }}
        OPTIONAL {{ ?hq wdt:P17 ?country. }}
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT 1
    """

    results = query_wikidata(sparql)

    if not results:
        return None

    result = results[0]

    return {
        'ticker': result.get('ticker', {}).get('value'),
        'exchange': result.get('exchangeLabel', {}).get('value'),
        'revenue_usd': int(float(result['revenue']['value'])) if 'revenue' in result else None,
        'employees': int(result['employees']['value']) if 'employees' in result else None,
        'hq_geonames_id': result.get('hqGeoNames', {}).get('value'),
        'hq_label': result.get('hqLabel', {}).get('value'),
        'country': result.get('countryLabel', {}).get('value'),
    }

def enrich_company_from_wikidata(cik: str) -> bool:
    """
    Enrich a single company with Wikidata data.

    Args:
        cik: Company CIK

    Returns:
        True if enriched, False otherwise
    """
    print(f"Enriching CIK {cik} from Wikidata...")

    # Find Wikidata QID
    qid = find_wikidata_by_cik(cik)

    if not qid:
        print(f"  ⚠ No Wikidata entry found for CIK {cik}")
        return False

    print(f"  → Found Wikidata {qid}")

    # Fetch company data
    data = get_wikidata_company_data(qid)

    if not data:
        print(f"  ⚠ No data found for {qid}")
        return False

    # Update company table
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE company
                SET wikidata_qid = %s,
                    revenue_usd = COALESCE(%s, revenue_usd),
                    employees = COALESCE(%s, employees),
                    updated_at = NOW()
                WHERE cik = %s
                RETURNING sec_legal_name
            """, (qid, data['revenue_usd'], data['employees'], cik))

            company = cur.fetchone()

            if not company:
                print(f"  ✗ Company CIK {cik} not found in database")
                return False

            print(f"  ✓ {company['sec_legal_name']}")
            print(f"    Revenue: ${data['revenue_usd']:,}" if data['revenue_usd'] else "    Revenue: N/A")
            print(f"    Employees: {data['employees']:,}" if data['employees'] else "    Employees: N/A")

            # Create evidence record for Wikidata enrichment
            cur.execute("""
                INSERT INTO evidence
                (source_system, source_record_id, evidence_type, confidence, license, url, observed_at)
                VALUES ('wikidata', %s, 'company_enrichment', 1.0, 'CC0', %s, NOW())
                ON CONFLICT (source_system, source_record_id) DO UPDATE
                SET observed_at = NOW()
                RETURNING id
            """, (qid, f"https://www.wikidata.org/wiki/{qid}"))

            evidence_id = cur.fetchone()['id']

            # Store HQ location if available
            if data['hq_geonames_id']:
                # First ensure location exists
                cur.execute("""
                    INSERT INTO location (geonames_id, name, country_code)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (geonames_id) DO NOTHING
                """, (data['hq_geonames_id'], data['hq_label'], data.get('country')))

                # Link company to location
                cur.execute("""
                    INSERT INTO company_location
                    (company_cik, location_id, location_type, evidence_id, valid_from)
                    VALUES (%s, %s, 'hq_operational', %s, CURRENT_DATE)
                    ON CONFLICT (company_cik, location_id, location_type, valid_from)
                    DO NOTHING
                """, (cik, data['hq_geonames_id'], evidence_id))

                print(f"    HQ: {data['hq_label']} (GeoNames:{data['hq_geonames_id']})")

            conn.commit()

    return True

def batch_enrich_companies(ciks: Optional[List[str]] = None,
                          rate_limit_delay: float = 1.0) -> Dict[str, int]:
    """
    Enrich all companies with Wikidata.

    Args:
        ciks: List of CIKs (None = all companies)
        rate_limit_delay: Delay between Wikidata queries

    Returns:
        Stats dict
    """
    if not ciks:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT cik FROM company ORDER BY cik")
                ciks = [row['cik'] for row in cur.fetchall()]

    stats = {'enriched': 0, 'not_found': 0, 'failed': 0}

    # Log start
    log_id = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingestion_log
                (phase, source_system, records_processed, started_at, status)
                VALUES ('enrichment', 'wikidata', %s, NOW(), 'running')
                RETURNING id
            """, (len(ciks),))
            log_id = cur.fetchone()['id']
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Phase 3: Wikidata Enrichment")
    print(f"{'='*60}")
    print(f"Enriching {len(ciks)} companies...")

    for i, cik in enumerate(ciks, 1):
        print(f"\n[{i}/{len(ciks)}]", end=" ")

        try:
            if enrich_company_from_wikidata(cik):
                stats['enriched'] += 1
            else:
                stats['not_found'] += 1

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
            """, (stats['enriched'], stats['not_found'] + stats['failed'], log_id))
            conn.commit()

    print(f"\n{'='*60}")
    print(f"Wikidata Enrichment Complete")
    print(f"{'='*60}")
    print(f"Enriched: {stats['enriched']}")
    print(f"Not found: {stats['not_found']}")
    print(f"Failed: {stats['failed']}")

    return stats

if __name__ == "__main__":
    batch_enrich_companies()
