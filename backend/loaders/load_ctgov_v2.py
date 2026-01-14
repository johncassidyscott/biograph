#!/usr/bin/env python3
"""
ClinicalTrials.gov v2 loader with entity resolution.

THIS IS THE REFERENCE IMPLEMENTATION showing how to use the entity resolver.

Key differences from v1:
1. Uses EntityResolver for all entity lookups (drugs, diseases, companies)
2. Tracks confidence scores on all edges
3. No duplicate entity creation
4. Proper canonical ID resolution
"""
from __future__ import annotations

import datetime as dt
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.entity_resolver import get_resolver, ResolvedEntity
from backend.loaders.load_ctgov import fetch_pages, extract  # Reuse fetch logic
from app.db import get_conn


def load_ctgov_v2(
    condition_queries: list[str],
    min_last_update: dt.date | None = None,
    max_last_update: dt.date | None = None,
) -> None:
    """
    Load ClinicalTrials.gov data using entity resolver.

    This version ensures:
    - No duplicate entities created
    - High-confidence matches for known drugs/diseases/companies
    - Confidence scores tracked on all relationships
    """

    resolver = get_resolver()
    resolver.load_lookup_tables()  # Pre-load for fast lookups

    inserted_trials = 0
    inserted_edges = 0
    low_confidence_edges = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for query in condition_queries:
                print(f"\nQuery: {query}")

                for raw in fetch_pages(query, page_size=200, count_total=False):
                    ex = extract(raw)
                    if not ex:
                        continue

                    # Date filter
                    if min_last_update and ex.last_update_posted and ex.last_update_posted < min_last_update:
                        continue
                    if max_last_update and ex.last_update_posted and ex.last_update_posted > max_last_update:
                        continue

                    trial_cid = f"NCT:{ex.nct_id}"

                    # Create trial entity (canonical NCT ID, always high confidence)
                    cur.execute(
                        """
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (kind, canonical_id) DO UPDATE
                          SET name = EXCLUDED.name, updated_at = NOW()
                        RETURNING id
                        """,
                        ("trial", trial_cid, ex.title or ex.nct_id),
                    )
                    trial_entity_id = cur.fetchone()[0]

                    # Upsert trial facts
                    cur.execute(
                        """
                        INSERT INTO trial (
                          nct_id, title, overall_status, phase_raw, phase_min, study_type,
                          start_date, primary_completion_date, completion_date, last_update_posted,
                          sponsor_name
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (nct_id) DO UPDATE SET
                          title = EXCLUDED.title,
                          overall_status = EXCLUDED.overall_status,
                          phase_raw = EXCLUDED.phase_raw,
                          phase_min = EXCLUDED.phase_min,
                          study_type = EXCLUDED.study_type,
                          start_date = EXCLUDED.start_date,
                          primary_completion_date = EXCLUDED.primary_completion_date,
                          completion_date = EXCLUDED.completion_date,
                          last_update_posted = EXCLUDED.last_update_posted,
                          sponsor_name = EXCLUDED.sponsor_name
                        """,
                        (
                            ex.nct_id, ex.title, ex.overall_status, ex.phase_raw,
                            ex.phase_min, ex.study_type, ex.start_date,
                            ex.primary_completion_date, ex.completion_date,
                            ex.last_update_posted, ex.sponsor_name,
                        ),
                    )
                    inserted_trials += 1

                    # Resolve sponsor company
                    if ex.sponsor_name:
                        company = resolver.resolve_company(ex.sponsor_name)

                        # Create edge with confidence score
                        cur.execute(
                            """
                            INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                            VALUES (%s, 'sponsored_by', %s, 'ctgov', %s)
                            ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                              SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, company.entity_id, company.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if company.confidence < 0.90:
                            low_confidence_edges += 1
                            print(f"    ⚠️  Low confidence company: {ex.sponsor_name} -> {company.name} ({company.confidence:.2f})")

                    # Resolve condition diseases
                    for condition_name in ex.conditions:
                        disease = resolver.resolve_disease(condition_name)

                        cur.execute(
                            """
                            INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                            VALUES (%s, 'for_condition', %s, 'ctgov', %s)
                            ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                              SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, disease.entity_id, disease.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if disease.confidence < 0.90:
                            low_confidence_edges += 1
                            print(f"    ⚠️  Low confidence disease: {condition_name} -> {disease.name} ({disease.confidence:.2f})")

                    # Resolve drug interventions
                    for itype, drug_name in ex.interventions:
                        if itype.upper() not in ("DRUG", "BIOLOGICAL"):
                            continue

                        drug = resolver.resolve_drug(drug_name)

                        cur.execute(
                            """
                            INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                            VALUES (%s, 'studies', %s, 'ctgov', %s)
                            ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                              SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, drug.entity_id, drug.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if drug.confidence < 0.90:
                            low_confidence_edges += 1
                            print(f"    ⚠️  Low confidence drug: {drug_name} -> {drug.name} ({drug.confidence:.2f})")

                conn.commit()

    print(f"\n✓ Trials inserted: {inserted_trials}")
    print(f"✓ Edges inserted: {inserted_edges}")
    print(f"⚠️  Low confidence edges (<0.90): {low_confidence_edges}")
    print(f"\nConfidence breakdown:")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    CASE
                        WHEN confidence >= 0.95 THEN 'High (0.95-1.0)'
                        WHEN confidence >= 0.85 THEN 'Good (0.85-0.95)'
                        WHEN confidence >= 0.70 THEN 'Medium (0.70-0.85)'
                        ELSE 'Low (<0.70)'
                    END as confidence_bucket,
                    COUNT(*) as count,
                    ROUND(AVG(confidence)::numeric, 2) as avg_confidence
                FROM edge
                WHERE source = 'ctgov'
                GROUP BY confidence_bucket
                ORDER BY avg_confidence DESC
            """)

            for row in cur.fetchall():
                bucket, count, avg = row
                print(f"  {bucket}: {count} edges (avg: {avg})")


if __name__ == "__main__":
    queries = [
        "obesity",
        "alzheimer disease",
        "KRAS AND non-small cell lung cancer",
    ]

    min_d = dt.date(2024, 1, 1)
    max_d = dt.date(2025, 1, 31)

    load_ctgov_v2(condition_queries=queries, min_last_update=min_d, max_last_update=max_d)
