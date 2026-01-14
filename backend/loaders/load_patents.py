#!/usr/bin/env python3
"""
USPTO patents loader - uses PatentsView API (official USPTO data source).

Fetches patent information for drugs in our graph.
PatentsView API docs: https://patentsview.org/apis/api-endpoints

Note: PatentsView is maintained by USPTO and provides free access to patent data.
"""
import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Optional
from app.db import get_conn

PATENTSVIEW_BASE = "https://search.patentsview.org/api/v1/patent"

def search_patents(drug_name: str, max_results: int = 10) -> List[Dict]:
    """
    Search PatentsView for patents mentioning a drug name.

    Returns list of patents with numbers, dates, titles, assignees.
    """
    # Query format for PatentsView API v1
    query = {
        "q": {
            "patent_title": drug_name
        },
        "f": [
            "patent_number",
            "patent_title",
            "patent_date",
            "patent_type",
            "assignee_organization",
            "cpc_subgroup_id"
        ],
        "o": {
            "per_page": max_results
        }
    }

    try:
        req = urllib.request.Request(
            PATENTSVIEW_BASE,
            data=json.dumps(query).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))

        patents = data.get("patents", [])
        return patents

    except Exception as e:
        print(f"  Warning: PatentsView search failed for '{drug_name}': {e}")
        return []

def load_patents(drug_list: List[Dict[str, str]]) -> None:
    """
    Load patent data for specific drugs.

    drug_list format:
    [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        ...
    ]

    Creates patent entities and links them to drugs.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_patents = 0
            inserted_edges = 0

            for drug_spec in drug_list:
                name = drug_spec.get("name")
                chembl_id = drug_spec.get("chembl_id")

                if not name or not chembl_id:
                    continue

                print(f"\nSearching patents: {name}")

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

                # Search patents
                patents = search_patents(name, max_results=5)
                print(f"  Found {len(patents)} patents")

                for patent in patents:
                    patent_num = patent.get("patent_number")
                    title = patent.get("patent_title", "")
                    patent_date = patent.get("patent_date")
                    assignees = patent.get("assignee_organization", [])

                    if not patent_num:
                        continue

                    # Get primary assignee (usually first one)
                    assignee = assignees[0] if assignees else None

                    # Insert patent entity
                    canonical_id = f"USPTO:{patent_num}"
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('patent', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                        """,
                        (canonical_id, title[:500] if title else patent_num),
                    )
                    patent_entity_id = cur.fetchone()[0]
                    inserted_patents += 1

                    # Create edge: patent --covers--> drug
                    cur.execute(
                        """
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'covers', %s, 'uspto')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                        """,
                        (patent_entity_id, drug_entity_id),
                    )
                    inserted_edges += cur.rowcount

                    # If assignee exists and matches a company, link them
                    if assignee:
                        cur.execute(
                            """
                            SELECT id FROM entity
                            WHERE kind = 'company' AND (
                                LOWER(name) = LOWER(%s)
                                OR EXISTS (
                                    SELECT 1 FROM alias
                                    WHERE entity_id = entity.id
                                    AND LOWER(alias) = LOWER(%s)
                                )
                            )
                            LIMIT 1
                            """,
                            (assignee, assignee),
                        )
                        company_result = cur.fetchone()
                        if company_result:
                            company_id = company_result[0]
                            # Create edge: company --filed--> patent
                            cur.execute(
                                """
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'filed', %s, 'uspto')
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                                """,
                                (company_id, patent_entity_id),
                            )
                            inserted_edges += cur.rowcount

                    print(f"  ✓ {patent_num}: {title[:60]}... ({patent_date})")

                time.sleep(1)  # Be polite to USPTO API

            conn.commit()

    print(f"\n✓ Patents inserted: {inserted_patents}")
    print(f"✓ Patent edges: {inserted_edges}")

if __name__ == "__main__":
    # POC drugs for patent search
    # Note: Patent search by drug name may have mixed results
    # More precise matching would require drug substance names or CAS numbers
    poc_drugs = [
        {"name": "Semaglutide", "chembl_id": "CHEMBL2109743"},
        {"name": "Tirzepatide", "chembl_id": "CHEMBL4297448"},
        {"name": "Lecanemab", "chembl_id": "CHEMBL2366541"},
        {"name": "Sotorasib", "chembl_id": "CHEMBL4297299"},
        {"name": "Adagrasib", "chembl_id": "CHEMBL4594668"},
    ]

    load_patents(poc_drugs)
