#!/usr/bin/env python3
"""
Crossref loader - enriches publications with DOI metadata and finds additional papers.

Crossref API: https://api.crossref.org
Free, open metadata for scholarly publications.
"""
import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
from app.db import get_conn

CROSSREF_BASE = "https://api.crossref.org/works"

def search_crossref(query: str, rows: int = 20) -> List[Dict]:
    """
    Search Crossref for publications matching query.

    Args:
        query: Search query (e.g., "semaglutide obesity")
        rows: Number of results to return

    Returns:
        List of publication records
    """
    params = {
        "query": query,
        "rows": str(rows),
        "select": "DOI,title,author,published-print,container-title,is-referenced-by-count"
    }

    url = f"{CROSSREF_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BioGraph/1.0 (mailto:research@biograph.io)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        items = data.get("message", {}).get("items", [])
        return items

    except Exception as e:
        print(f"  Warning: Crossref search failed for '{query}': {e}")
        return []

def load_crossref_publications(drug_queries: List[Dict[str, str]], max_per_query: int = 15) -> None:
    """
    Load publications from Crossref for drug queries.

    drug_queries format:
    [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743", "query": "semaglutide obesity treatment"},
        ...
    ]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted = 0
            inserted_edges = 0

            for drug_spec in drug_queries:
                name = drug_spec.get("name")
                chembl_id = drug_spec.get("chembl_id")
                query = drug_spec.get("query")

                if not name or not chembl_id or not query:
                    continue

                print(f"\nSearching Crossref: {query}")

                # Get drug entity
                cur.execute(
                    """
                    SELECT id FROM entity
                    WHERE kind = 'drug' AND canonical_id = %s
                    """,
                    (f"CHEMBL:{chembl_id}",),
                )
                result = cur.fetchone()
                if not result:
                    print(f"  Warning: Drug {chembl_id} not found")
                    continue

                drug_entity_id = result[0]

                # Search Crossref
                publications = search_crossref(query, rows=max_per_query)
                print(f"  Found {len(publications)} publications")

                for pub in publications:
                    doi = pub.get("DOI")
                    title_list = pub.get("title", [])
                    title = title_list[0] if title_list else ""

                    if not doi or not title:
                        continue

                    # Get journal name
                    journal_list = pub.get("container-title", [])
                    journal = journal_list[0] if journal_list else ""

                    # Get citation count
                    citation_count = pub.get("is-referenced-by-count", 0)

                    # Insert publication entity
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

                    # Create edge: publication --mentions--> drug
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'mentions', %s, 'crossref')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """,
                        (pub_entity_id, drug_entity_id),
                    )
                    inserted_edges += cur.rowcount

                time.sleep(1)  # Be polite to Crossref

            conn.commit()

    print(f"\n✓ Crossref publications inserted: {inserted}")
    print(f"✓ Publication-drug edges: {inserted_edges}")

if __name__ == "__main__":
    # POC queries for Crossref
    poc_queries = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743", "query": "semaglutide obesity weight loss"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448", "query": "tirzepatide diabetes obesity"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541", "query": "lecanemab alzheimer amyloid"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299", "query": "sotorasib KRAS lung cancer"},
        {"name": "Adagrasib", "chembl_id": "CHEMBL4594668", "query": "adagrasib KRAS cancer"},
    ]

    load_crossref_publications(poc_queries, max_per_query=15)
