#!/usr/bin/env python3
"""
NIH grants loader - fetches grant funding data for disease areas.

Uses NIH RePORTER API (official NIH research funding database).
API docs: https://api.reporter.nih.gov/

Discovers grants funding research in our POC disease areas.
"""
import json
import urllib.request
import time
from typing import List, Dict
from app.db import get_conn

REPORTER_BASE = "https://api.reporter.nih.gov/v2/projects/search"

def search_nih_grants(query: str, fiscal_years: List[int], limit: int = 50) -> List[Dict]:
    """
    Search NIH RePORTER for grants.

    Args:
        query: Disease or research area to search
        fiscal_years: List of years to search (e.g., [2023, 2024])
        limit: Maximum results

    Returns list of grant records
    """
    payload = {
        "criteria": {
            "project_title": query,
            "fiscal_years": fiscal_years
        },
        "limit": limit,
        "offset": 0
    }

    try:
        req = urllib.request.Request(
            REPORTER_BASE,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        results = data.get("results", [])
        return results

    except Exception as e:
        print(f"  Warning: NIH RePORTER search failed for '{query}': {e}")
        return []

def load_nih_grants_for_diseases(disease_queries: List[Dict[str, str]]) -> None:
    """
    Load NIH grants for specific disease areas.

    disease_queries format:
    [
        {"disease": "Obesity", "mesh_id": "D009765", "query": "obesity"},
        ...
    ]
    """
    fiscal_years = [2023, 2024]  # Recent grants

    with get_conn() as conn:
        with conn.cursor() as cur:
            inserted_grants = 0
            inserted_edges = 0

            for disease_spec in disease_queries:
                disease_name = disease_spec.get("disease")
                mesh_id = disease_spec.get("mesh_id")
                query = disease_spec.get("query")

                if not disease_name or not mesh_id or not query:
                    continue

                print(f"\nSearching NIH grants: {query}")

                # Get disease entity
                cur.execute("""
                    SELECT id FROM entity
                    WHERE kind = 'disease' AND canonical_id = %s
                """, (f"MESH:{mesh_id}",))

                disease_result = cur.fetchone()
                if not disease_result:
                    print(f"  Warning: Disease {mesh_id} not found")
                    continue

                disease_entity_id = disease_result[0]

                # Search grants
                grants = search_nih_grants(query, fiscal_years, limit=25)
                print(f"  Found {len(grants)} grants")

                for grant in grants:
                    project_num = grant.get("project_num")
                    title = grant.get("project_title", "")
                    pi_names = grant.get("principal_investigators", [])
                    org_name = grant.get("organization", {}).get("org_name", "")
                    award_amount = grant.get("award_amount")
                    fiscal_year = grant.get("fiscal_year")

                    if not project_num or not title:
                        continue

                    # Insert grant entity
                    canonical_id = f"NIH:{project_num}"
                    cur.execute("""
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('grant', %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              updated_at = NOW()
                        RETURNING id
                    """, (canonical_id, title[:500]))

                    grant_entity_id = cur.fetchone()[0]
                    inserted_grants += 1

                    # Link grant to disease
                    cur.execute("""
                        INSERT INTO edge (src_id, predicate, dst_id, source)
                        VALUES (%s, 'funds_research_on', %s, 'nih_reporter')
                        ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                    """, (grant_entity_id, disease_entity_id))
                    inserted_edges += cur.rowcount

                    # Link grant to organization (if we have it)
                    if org_name:
                        # Try to find organization entity
                        cur.execute("""
                            SELECT id FROM entity
                            WHERE kind IN ('company', 'academic')
                              AND (LOWER(name) = LOWER(%s)
                                   OR EXISTS (
                                       SELECT 1 FROM alias
                                       WHERE entity_id = entity.id
                                         AND LOWER(alias) = LOWER(%s)
                                   ))
                            LIMIT 1
                        """, (org_name, org_name))

                        org_result = cur.fetchone()
                        if org_result:
                            org_entity_id = org_result[0]

                            cur.execute("""
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'awarded_to', %s, 'nih_reporter')
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                            """, (grant_entity_id, org_entity_id))
                            inserted_edges += cur.rowcount

                    # Link grant to PI (if we have them)
                    for pi in pi_names[:3]:  # Limit to first 3 PIs
                        pi_name = pi.get("full_name")
                        if not pi_name:
                            continue

                        # Try to find researcher entity
                        normalized = pi_name.lower().replace(",", "").replace(".", "")
                        cur.execute("""
                            SELECT id FROM entity
                            WHERE kind = 'person'
                              AND LOWER(REPLACE(REPLACE(name, ',', ''), '.', '')) LIKE %s
                            LIMIT 1
                        """, (f"%{normalized}%",))

                        pi_result = cur.fetchone()
                        if pi_result:
                            pi_entity_id = pi_result[0]

                            cur.execute("""
                                INSERT INTO edge (src_id, predicate, dst_id, source)
                                VALUES (%s, 'awarded_to', %s, 'nih_reporter')
                                ON CONFLICT (src_id, predicate, dst_id) DO NOTHING
                            """, (grant_entity_id, pi_entity_id))
                            inserted_edges += cur.rowcount

                    amount_str = f"${award_amount:,}" if award_amount else "N/A"
                    print(f"  ✓ {project_num}: {title[:60]}... ({fiscal_year}, {amount_str})")

                time.sleep(1)  # Be polite to NIH

            conn.commit()

    print(f"\n✓ NIH grants inserted: {inserted_grants}")
    print(f"✓ Grant edges created: {inserted_edges}")

if __name__ == "__main__":
    # POC disease queries for NIH grants
    poc_diseases = [
        {"disease": "Obesity", "mesh_id": "D009765", "query": "obesity"},
        {"disease": "Alzheimer's Disease", "mesh_id": "D000544", "query": "alzheimer"},
        {"disease": "Lung Cancer", "mesh_id": "D002289", "query": "KRAS lung cancer"},
    ]

    load_nih_grants_for_diseases(poc_diseases)
