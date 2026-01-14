#!/usr/bin/env python3
"""
bioRxiv/medRxiv preprints loader - fetches preprints from bioRxiv/medRxiv APIs.

bioRxiv: https://api.biorxiv.org
medRxiv: https://api.medrxiv.org

Both are free, public repositories for life sciences and medicine preprints.
"""
import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict
from datetime import datetime, timedelta
from backend.app.db import get_conn

BIORXIV_BASE = "https://api.biorxiv.org/details/biorxiv"
MEDRXIV_BASE = "https://api.medrxiv.org/details/medrxiv"

def search_preprints(server: str, start_date: str, end_date: str, cursor: int = 0) -> Dict:
    """
    Search bioRxiv or medRxiv for preprints in date range.

    Args:
        server: "biorxiv" or "medrxiv"
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        cursor: pagination cursor

    Returns:
        Response dict with preprints
    """
    base_url = BIORXIV_BASE if server == "biorxiv" else MEDRXIV_BASE
    url = f"{base_url}/{start_date}/{end_date}/{cursor}/json"

    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data
    except Exception as e:
        print(f"  Warning: {server} API error: {e}")
        return {"messages": [], "collection": []}

def load_preprints_for_drugs(drug_keywords: List[str], days_back: int = 365) -> None:
    """
    Load recent preprints mentioning specific drug keywords.

    Args:
        drug_keywords: List of drug names to search for in titles/abstracts
        days_back: How many days back to search (default 365)
    """
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"Searching preprints from {start_str} to {end_str}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted = 0
            inserted_edges = 0

            # Get drug entities for linking
            drug_map = {}
            for keyword in drug_keywords:
                cur.execute(
                    """
                    SELECT id, name FROM entity
                    WHERE kind = 'drug' AND LOWER(name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (keyword,),
                )
                result = cur.fetchone()
                if result:
                    drug_map[keyword.lower()] = result[0]

            # Search both bioRxiv and medRxiv
            for server in ["biorxiv", "medrxiv"]:
                print(f"\nSearching {server}...")

                data = search_preprints(server, start_str, end_str, cursor=0)
                preprints = data.get("collection", [])
                print(f"  Found {len(preprints)} preprints")

                for preprint in preprints:
                    doi = preprint.get("doi")
                    title = preprint.get("title", "")
                    abstract = preprint.get("abstract", "")
                    posted_date = preprint.get("date")

                    if not doi or not title:
                        continue

                    # Check if any drug keywords appear in title or abstract
                    text = (title + " " + abstract).lower()
                    matching_drugs = [k for k in drug_keywords if k.lower() in text]

                    if not matching_drugs:
                        continue

                    # Insert preprint as publication entity
                    canonical_id = f"DOI:{doi}"
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('publication', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                        """,
                        (canonical_id, title[:500]),
                    )
                    pub_entity_id = cur.fetchone()[0]
                    inserted += 1

                    # Link to matching drugs
                    for drug_keyword in matching_drugs:
                        drug_id = drug_map.get(drug_keyword.lower())
                        if drug_id:
                            cur.execute(
                                """
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'mentions', %s, %s)
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                                """,
                                (pub_entity_id, drug_id, server),
                            )
                            inserted_edges += cur.rowcount

                    if inserted % 10 == 0:
                        print(f"  Processed {inserted} relevant preprints...")

                time.sleep(1)  # Be polite

            conn.commit()

    print(f"\n✓ Preprints inserted: {inserted}")
    print(f"✓ Preprint-drug edges: {inserted_edges}")

if __name__ == "__main__":
    # POC drug keywords for preprint search
    poc_keywords = [
        "Semaglutide",
        "Tirzepatide",
        "Liraglutide",
        "GLP-1",
        "Lecanemab",
        "Aducanumab",
        "Alzheimer",
        "Sotorasib",
        "Adagrasib",
        "KRAS",
    ]

    # Search last year of preprints
    load_preprints_for_drugs(poc_keywords, days_back=365)
