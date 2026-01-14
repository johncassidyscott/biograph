#!/usr/bin/env python3
"""
Company enrichment - adds business metadata to discovered companies.

Enriches companies with:
1. SEC CIK identifiers (for public companies)
2. Stock ticker symbols
3. Company type classification

Uses SEC EDGAR company list (free, official government source).
"""
import json
import urllib.request
from typing import Dict, Optional
from backend.app.db import get_conn

SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"

def fetch_sec_company_list() -> Dict[str, Dict]:
    """
    Fetch official SEC company list with CIK numbers.

    Returns dict mapping normalized company names to SEC data.
    """
    print("Fetching SEC company list...")

    req = urllib.request.Request(
        SEC_COMPANY_TICKERS,
        headers={"User-Agent": "BioGraph/1.0 research@biograph.io"}
    )

    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode("utf-8"))

    # Normalize for matching
    sec_companies = {}
    for key, company in data.items():
        cik = str(company["cik_str"]).zfill(10)  # Pad to 10 digits
        ticker = company.get("ticker", "")
        title = company.get("title", "")

        # Normalize company name
        normalized = title.lower()
        # Remove common suffixes for better matching
        for suffix in [" inc", " corp", " corporation", " company", " co", " llc", " ltd"]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()

        normalized = normalized.replace(",", "").replace(".", "")

        sec_companies[normalized] = {
            "cik": cik,
            "ticker": ticker,
            "official_name": title
        }

    print(f"  Loaded {len(sec_companies)} SEC companies")
    return sec_companies

def normalize_for_matching(name: str) -> str:
    """Normalize company name for fuzzy matching"""
    normalized = name.lower()

    # Remove suffixes
    for suffix in [
        " inc.", " inc", " corporation", " corp.", " corp", " company",
        " co.", " co", " llc", " ltd.", " ltd", " limited", " plc",
        " a/s", " ab", " gmbh", " s.a.", ", inc", ", llc"
    ]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()

    # Remove punctuation
    normalized = normalized.replace(",", "").replace(".", "").replace("&", "and")

    # Remove "the" prefix
    if normalized.startswith("the "):
        normalized = normalized[4:]

    return " ".join(normalized.split())

def match_company_to_sec(company_name: str, sec_data: Dict) -> Optional[Dict]:
    """
    Try to match a company name to SEC database.

    Uses fuzzy matching strategies.
    """
    normalized = normalize_for_matching(company_name)

    # Direct match
    if normalized in sec_data:
        return sec_data[normalized]

    # Try partial matches
    for sec_name, data in sec_data.items():
        # Company name contains SEC name or vice versa
        if normalized in sec_name or sec_name in normalized:
            # Make sure it's not a short spurious match
            if len(sec_name) > 3 and len(normalized) > 3:
                return data

    return None

def enrich_discovered_companies() -> None:
    """
    Enrich discovered companies with SEC CIK data where available.
    """
    sec_data = fetch_sec_company_list()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get all discovered companies
            cur.execute("""
                SELECT id, canonical_id, name
                FROM entity
                WHERE kind = 'company'
                  AND canonical_id LIKE 'DISCOVERED:%'
            """)

            companies = cur.fetchall()
            print(f"\nEnriching {len(companies)} discovered companies...")

            matched = 0
            updated = 0

            for company_id, canonical_id, name in companies:
                # Try to match to SEC
                sec_match = match_company_to_sec(name, sec_data)

                if sec_match:
                    cik = sec_match["cik"]
                    ticker = sec_match["ticker"]
                    official_name = sec_match["official_name"]

                    matched += 1

                    # Update canonical_id to use CIK
                    new_canonical_id = f"CIK:{cik}"

                    print(f"  ✓ {name} → {official_name} (CIK:{cik}, {ticker})")

                    # Update entity
                    cur.execute("""
                        UPDATE entity
                        SET canonical_id = %s,
                            name = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (new_canonical_id, official_name, company_id))

                    # Add ticker as alias if present
                    if ticker:
                        cur.execute("""
                            INSERT INTO alias (entity_id, alias, source)
                            VALUES (%s, %s, 'sec')
                            ON CONFLICT DO NOTHING
                        """, (company_id, ticker))

                    updated += 1

            conn.commit()

    print(f"\n✓ Companies matched to SEC: {matched}/{len(companies)}")
    print(f"✓ Companies enriched with CIK: {updated}")

if __name__ == "__main__":
    enrich_discovered_companies()
