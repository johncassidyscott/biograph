#!/usr/bin/env python3
"""
PubMed publications loader - fetch recent papers for POC drugs.

Uses NCBI E-utilities API:
- esearch: search for papers by drug name
- efetch: get paper details (title, authors, abstract)

API docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from app.db import get_conn

ESEARCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

def search_pubmed(query: str, max_results: int = 20) -> List[str]:
    """
    Search PubMed and return list of PMIDs.

    Args:
        query: Search query (e.g., "Semaglutide AND obesity")
        max_results: Maximum number of results to return

    Returns:
        List of PMIDs as strings
    """
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "pub_date",  # Most recent first
        "datetype": "pdat",
        "mindate": "2024/01/01",  # POC time window
        "maxdate": "2025/01/31",
    }

    url = f"{ESEARCH_BASE}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read().decode("utf-8"))

        pmids = data.get("esearchresult", {}).get("idlist", [])
        return pmids

    except Exception as e:
        print(f"Warning: PubMed search failed for '{query}': {e}")
        return []

def fetch_pubmed_details(pmids: List[str]) -> List[Dict]:
    """
    Fetch article details for given PMIDs.

    Returns list of article dicts with: pmid, title, authors, abstract
    """
    if not pmids:
        return []

    # Batch PMIDs (max 200 per request)
    pmid_str = ",".join(pmids[:200])

    params = {
        "db": "pubmed",
        "id": pmid_str,
        "retmode": "xml",
    }

    url = f"{EFETCH_BASE}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url) as r:
            xml_data = r.read()

        root = ET.fromstring(xml_data)
        articles = []

        for article in root.findall(".//PubmedArticle"):
            pmid_elem = article.find(".//PMID")
            title_elem = article.find(".//ArticleTitle")
            abstract_elem = article.find(".//AbstractText")

            if pmid_elem is None or title_elem is None:
                continue

            pmid = pmid_elem.text
            title = title_elem.text or ""
            abstract = abstract_elem.text if abstract_elem is not None else ""

            # Get authors
            authors = []
            for author in article.findall(".//Author"):
                lastname = author.find("LastName")
                forename = author.find("ForeName")
                if lastname is not None:
                    name = lastname.text
                    if forename is not None:
                        name = f"{forename.text} {name}"
                    authors.append(name)

            articles.append({
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
            })

        return articles

    except Exception as e:
        print(f"Warning: Failed to fetch PubMed details: {e}")
        return []

def load_pubmed_for_drugs(drug_queries: List[Dict[str, str]], max_per_drug: int = 10) -> None:
    """
    Load recent PubMed publications for specific drugs.

    drug_queries format:
    [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743", "query": "Semaglutide AND obesity"},
        ...
    ]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_pubs = 0
            inserted_edges = 0

            for drug_spec in drug_queries:
                name = drug_spec.get("name")
                chembl_id = drug_spec.get("chembl_id")
                query = drug_spec.get("query")

                if not name or not chembl_id or not query:
                    continue

                print(f"\nSearching PubMed: {query}")

                # Search PubMed
                pmids = search_pubmed(query, max_results=max_per_drug)
                print(f"  Found {len(pmids)} papers")

                if not pmids:
                    continue

                time.sleep(0.5)  # Be polite to NCBI

                # Fetch details
                articles = fetch_pubmed_details(pmids)
                print(f"  Retrieved {len(articles)} article details")

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

                # Insert publications and link to drug
                for article in articles:
                    pmid = article["pmid"]
                    title = article["title"]
                    abstract = article.get("abstract", "")

                    # Insert publication entity
                    canonical_id = f"PMID:{pmid}"
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('publication', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                        """,
                        (canonical_id, title[:500]),  # Limit title length
                    )
                    pub_entity_id = cur.fetchone()[0]
                    inserted_pubs += 1

                    # Create edge: publication --mentions--> drug
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'mentions', %s, 'pubmed')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """,
                        (pub_entity_id, drug_entity_id),
                    )
                    inserted_edges += cur.rowcount

                time.sleep(0.5)  # Be polite

            conn.commit()

    print(f"\n✓ Publications inserted: {inserted_pubs}")
    print(f"✓ Publication-drug edges: {inserted_edges}")

if __name__ == "__main__":
    # POC queries - recent papers for key drugs
    poc_queries = [
        # Obesity drugs
        {
            "name": "Semaglutide",
            "chembl_id": "CHEMBL2109743",
            "query": "Semaglutide AND (obesity OR weight loss)",
        },
        {
            "name": "Tirzepatide",
            "chembl_id": "CHEMBL4297448",
            "query": "Tirzepatide AND (obesity OR diabetes)",
        },
        # Alzheimer's drugs
        {
            "name": "Lecanemab",
            "chembl_id": "CHEMBL2366541",
            "query": "Lecanemab AND Alzheimer",
        },
        {
            "name": "Aducanumab",
            "chembl_id": "CHEMBL4297072",
            "query": "Aducanumab AND Alzheimer",
        },
        # KRAS inhibitors
        {
            "name": "Sotorasib",
            "chembl_id": "CHEMBL4297299",
            "query": "Sotorasib AND (KRAS OR lung cancer)",
        },
        {
            "name": "Adagrasib",
            "chembl_id": "CHEMBL4594668",
            "query": "Adagrasib AND (KRAS OR cancer)",
        },
    ]

    load_pubmed_for_drugs(poc_queries, max_per_drug=10)
